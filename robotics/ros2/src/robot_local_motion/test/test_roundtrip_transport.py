"""Real DDS/MPPI round trip with synthetic sensors and isolated actuator output."""
import json
import math
import os
from pathlib import Path
import subprocess
import signal
import threading
import time
import pytest

pytest.importorskip('rclpy')
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from std_msgs.msg import Header, String
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster
from robot_local_motion.msg import TargetObservation
from robot_local_motion_runtime.server import LocalMotionServer
from robot_local_motion_runtime.roundtrip_demo import UwbRoundTripDemo
from test_task_transport import World, stop_owned_planner
from rclpy.task import Future
from types import SimpleNamespace


class DualWorld(World):
    def __init__(self):
        super().__init__()
        self.odom_child_frame='base_link';self.body_height=.38
        self.frisbee_x = 10.0
        self.owner_x = 0.0
        self.owner_enabled = True
        self.frisbee_enabled = True
        self.samples = 0
        self.fixed_obstacles=[]
        self.body_tf=StaticTransformBroadcaster(self)
        body=TransformStamped();body.header=Header(stamp=self.get_clock().now().to_msg(),frame_id='base_footprint')
        body.child_frame_id='base_link';body.transform.translation.z=.38;body.transform.rotation.w=1.0
        self.body_tf.sendTransform(body)
    def cloud_data(self):
        return [((x-self.x)*math.cos(self.yaw)+(y-self.y)*math.sin(self.yaw),
                 -(x-self.x)*math.sin(self.yaw)+(y-self.y)*math.cos(self.yaw),0.)
                for x,y in self.fixed_obstacles]
    def tick(self):
        super().tick()
        if not self.inputs:return
        self.samples += 1
        stamp = self.get_clock().now().to_msg()
        if self.samples%5:return  # actual dual-tag hardware is approximately 10 Hz
        for identity, x in [('0x87654322',self.owner_x),('0x87654324',self.frisbee_x)]:
            msg=TargetObservation();msg.header=Header(stamp=stamp,frame_id='base_footprint')
            msg.source='uwb_multitag';msg.target_id=identity;msg.sequence=self.samples
            msg.position.x=(x-self.x)*math.cos(self.yaw)-self.y*math.sin(self.yaw)
            msg.position.y=-(x-self.x)*math.sin(self.yaw)-self.y*math.cos(self.yaw)
            msg.valid=True;msg.confidence=1.0
            if ((identity=='0x87654322' and not self.owner_enabled)
                    or (identity=='0x87654324' and not self.frisbee_enabled)):
                msg.valid=False;msg.confidence=0.0
            self.target.publish(msg)


def until(predicate, timeout=55):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.02)
    assert predicate(), 'round-trip condition timed out'


@pytest.fixture(scope='module')
def round_stack(tmp_path_factory):
    assert os.environ.get('ROS_LOCALHOST_ONLY')=='1' and os.environ.get('ROS_DOMAIN_ID')=='227'
    directory=tmp_path_factory.mktemp('roundtrip-dds')
    log=(directory/'planner.log').open('w')
    from ament_index_python.packages import get_package_share_directory as share
    profile=str(Path(share('robot_local_motion'))/'config/lingmao_roundtrip.yaml')
    args=['ros2','run','go2_uwb_local_follow','local_velocity_planner_node','--ros-args',
        '--params-file',str(Path(share('go2_uwb_local_follow'))/'config/local_velocity_planner.yaml'),
        '--params-file',profile]
    params={'enable_motion':'true','enable_task_parameters':'true','min_linear_speed':'0.10','odom_topic':'/test/odom',
        'odom_child_frame':'base_link','obstacle_topic':'/test/cloud',
        'nominal_cmd_topic':'/robot_local_motion/nominal_cmd','final_cmd_topic':'/robot_local_motion/final_cmd',
        'cmd_vel_topic':'/test/planner_raw','diagnostics_topic':'/robot_local_motion/planner_diagnostics'}
    for key,value in params.items():args+=['-p',key+':='+value]
    planner=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    server=world=demo=executor=thread=None
    try:
        rclpy.init(args=['--ros-args','--params-file',profile,'-p','enable_motion:=true',
            '-p','odom_topic:=/test/odom','-p','odom_child_frame:=base_link',
            '-p','obstacle_topic:=/test/cloud','-p','cmd_vel_topic:=/test/cmd_vel',
            '-p','min_linear_speed:=0.10','-p','action_name:=/uwb_roundtrip/local_motion/execute'])
        server=LocalMotionServer();world=DualWorld()
        demo=UwbRoundTripDemo(parameter_overrides=[Parameter('owner_id',value='0x87654322'),
            Parameter('frisbee_id',value='0x87654324'), Parameter('frisbee_distance_m',value=.5)])
        statuses=[]
        world.create_subscription(String,'/uwb_roundtrip/status',lambda msg:statuses.append((time.monotonic(),json.loads(msg.data))),10)
        executor=MultiThreadedExecutor(num_threads=4)
        for node in (server,world,demo):executor.add_node(node)
        thread=threading.Thread(target=executor.spin);thread.start()
        until(lambda:demo.client.server_is_ready() and demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),8)
        yield server,world,demo,statuses
    finally:
        if demo is not None:
            (directory/'final-state.json').write_text(json.dumps({'state':demo.machine.state,
                'outcome':demo.machine.outcome,'message':demo.machine.message,'history':demo.history,
                'odom_age':time.monotonic()-demo.odom_at,'world_pose':[world.x,world.y,world.yaw],
                'last_statuses':statuses[-6:]},indent=2))
        if demo is not None and demo.machine.busy:
            demo.request_cancel()
            end=time.monotonic()+8
            while demo.machine.pending is not None and time.monotonic()<end:time.sleep(.05)
        stop_owned_planner(planner)
        if executor is not None:executor.shutdown()
        if thread is not None:
            thread.join(timeout=5)
            assert not thread.is_alive()
        for node in (demo,world,server):
            if node is not None:node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        log.close()


@pytest.mark.parametrize('distance',[10.0,5.0])
def test_roundtrip_waits_three_seconds_and_returns_to_owner_with_requested_limits(round_stack,distance):
    server,world,demo,statuses=round_stack
    world.owner_x=world.x
    world.frisbee_x=world.x+distance
    time.sleep(.2)
    until(lambda:demo.ready_target('0x87654324',time.monotonic()))
    started=time.monotonic()
    assert demo.start_roundtrip()[0]
    until(lambda:demo.machine.state in ('DWELL','FAILED','RECOVERY_REQUIRED'))
    assert demo.machine.state=='DWELL',(demo.machine.outcome,demo.machine.message)
    # The outbound stop must use the closer frisbee distance; return still uses 1 m.
    assert .5 <= math.hypot(world.frisbee_x-world.x,world.y) <= .75
    dwell_started=demo.machine.dwell_started
    until(lambda:demo.machine.state in ('RETURN_OWNER','FAILED','RECOVERY_REQUIRED'))
    assert demo.machine.state=='RETURN_OWNER',demo.machine.message
    assert demo.request_sent_at-dwell_started>=3.0
    assert all(abs(v)<=1e-9 and abs(w)<=1e-9 for at,v,w in world.commands if dwell_started+.1<=at<dwell_started+3.0)
    until(lambda:demo.machine.state in ('DONE','FAILED','RECOVERY_REQUIRED'))
    assert demo.machine.state=='DONE', (demo.machine.outcome,demo.machine.message)
    assert demo.machine.stop_confirmed
    assert [row['target_id'] for row in demo.history]==['0x87654324','0x87654322']
    assert all(row['stop_confirmed'] for row in demo.history)
    assert .8 <= math.hypot(world.x-world.owner_x,world.y) <= 1.25
    commands=[(v,w) for at,v,w in world.commands if at>=started]
    assert max(abs(v) for v,w in commands)>.8
    assert all(abs(v)<=1.0+1e-6 and abs(w)<=1.2+1e-6 for v,w in commands)
    assert not server.reserved and not server.recovery_locked


def test_cancel_during_three_second_dwell_never_dispatches_return(round_stack):
    _,world,demo,_=round_stack
    world.frisbee_x=world.x+1.45
    time.sleep(.1)
    until(lambda:demo.ready_target('0x87654324',time.monotonic()))
    assert demo.start_roundtrip()[0]
    until(lambda:demo.machine.state in ('DWELL','FAILED','RECOVERY_REQUIRED'))
    assert demo.machine.state=='DWELL',(demo.machine.outcome,demo.machine.message)
    demo.request_cancel()
    time.sleep(3.2)
    assert demo.machine.state=='CANCELED' and demo.machine.stop_confirmed
    assert len(demo.history)==1 and demo.history[0]['target_id']=='0x87654324'
    assert demo.machine.pending is None


def test_process_sigterm_settles_owned_goal_before_exit(round_stack,tmp_path):
    server,world,_,_=round_stack
    world.frisbee_x=world.x+2.0
    time.sleep(.1)
    args=['ros2','run','robot_local_motion','uwb_roundtrip_demo','--ros-args',
        '-r','__node:=uwb_roundtrip_shutdown_probe','-p','enable_motion:=true','-p','autostart:=true',
        '-p','owner_id:=0x87654322','-p','frisbee_id:=0x87654324',
        '-p','odom_topic:=/test/odom','-p','odom_child_frame:=base_link',
        '-p','action_name:=/uwb_roundtrip/local_motion/execute']
    with (tmp_path/'shutdown-demo.log').open('w') as log:
        process=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            until(lambda:server.active is not None and abs(world.v)>.05,10)
            task=server.active
            os.killpg(process.pid,signal.SIGTERM)
            until(lambda:not server.reserved and server.active is None,8)
            assert task.result.outcome=='CANCELED' and task.result.stop_confirmed
            assert abs(world.v)<1e-9 and abs(world.w)<1e-9
            process.wait(timeout=5)
        finally:
            stop_owned_planner(process)


def test_owner_hidden_behind_robot_is_reacquired_after_search_turn(round_stack):
    _,world,demo,_=round_stack
    world.owner_x=world.x-1.8
    world.frisbee_x=world.x+1.45
    world.owner_enabled=False
    time.sleep(.1)
    assert demo.start_roundtrip()[0]
    until(lambda:demo.machine.search_turns==1)
    assert demo.machine.state=='ACQUIRE_OWNER'
    world.owner_enabled=True
    until(lambda:demo.machine.state in ('DONE','FAILED','RECOVERY_REQUIRED'))
    assert demo.machine.state=='DONE',(demo.machine.outcome,demo.machine.message)
    assert [row['mode'] for row in demo.history]==['approach','turn','approach']
    assert demo.history[-1]['target_id']=='0x87654322'
    assert all(row['stop_confirmed'] for row in demo.history)



def test_unbounded_roundtrip_continues_beyond_thirty_seconds_in_each_leg(round_stack,tmp_path):
    server,world,demo,_=round_stack
    previous_speed=demo.speed
    evidence={'approach_timeout_sec':demo.machine.config.approach_timeout_sec,'motion_speed_cap':.2}
    path=tmp_path/'long-approach-evidence.json'
    try:
        demo.speed=.2;world.owner_x=world.x;world.frisbee_x=world.x+9.0
        time.sleep(.2)
        until(lambda:demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),5)
        assert demo.start_roundtrip()[0]
        outbound_at=demo.request_sent_at
        until(lambda:time.monotonic()-outbound_at>=31 or demo.machine.state!='APPROACH_FRISBEE',40)
        assert demo.machine.state=='APPROACH_FRISBEE',(demo.machine.outcome,demo.machine.message)
        assert server.active.p['timeout_sec']==0 and not demo.machine.cancel_requested
        assert any(abs(v)>.05 for at,v,w in world.commands if at>=outbound_at+30)
        evidence['outbound_after_30_sec']='ACTIVE';path.write_text(json.dumps(evidence,indent=2))
        until(lambda:demo.machine.state in ('DWELL','FAILED','RECOVERY_REQUIRED'),60)
        assert demo.machine.state=='DWELL',(demo.machine.outcome,demo.machine.message)
        evidence['outbound_elapsed_sec']=demo.machine.dwell_started-outbound_at
        assert .5<=math.hypot(world.frisbee_x-world.x,world.y)<=.75
        until(lambda:demo.machine.state in ('RETURN_OWNER','FAILED','RECOVERY_REQUIRED'),8)
        assert demo.machine.state=='RETURN_OWNER'
        return_at=demo.request_sent_at
        until(lambda:time.monotonic()-return_at>=31 or demo.machine.state!='RETURN_OWNER',40)
        assert demo.machine.state=='RETURN_OWNER',(demo.machine.outcome,demo.machine.message)
        assert server.active.p['timeout_sec']==0 and not demo.machine.cancel_requested
        evidence['return_after_30_sec']='ACTIVE';path.write_text(json.dumps(evidence,indent=2))
        until(lambda:demo.machine.state in ('DONE','FAILED','RECOVERY_REQUIRED'),60)
        assert demo.machine.state=='DONE',(demo.machine.outcome,demo.machine.message)
        assert demo.machine.stop_confirmed and all(x['stop_confirmed'] for x in demo.history)
        assert .8<=math.hypot(world.x-world.owner_x,world.y)<=1.25
        evidence.update(return_elapsed_sec=demo.history[-1]['at_monotonic']-return_at,
                        outcome=demo.machine.outcome,stop_confirmed=demo.machine.stop_confirmed)
        assert evidence['outbound_elapsed_sec']>30 and evidence['return_elapsed_sec']>30
        path.write_text(json.dumps(evidence,indent=2))
    finally:
        demo.speed=previous_speed
        if demo.machine.busy:
            demo.request_cancel()
            until(lambda:demo.machine.pending is None,8)


@pytest.mark.parametrize('fault,outcome',[('target_loss','INPUT_LOST')])
def test_unbounded_approach_still_stops_on_fault(round_stack,fault,outcome):
    server,world,demo,_=round_stack
    world.owner_x=world.x;world.frisbee_x=world.x+4.0
    try:
        time.sleep(.2)
        until(lambda:demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),5)
        assert demo.start_roundtrip()[0]
        until(lambda:server.active is not None and server.active.phase=='ACTIVE',5)
        assert server.active.p['timeout_sec']==0
        if fault=='target_loss':world.frisbee_enabled=False
        else:world.freeze=True
        until(lambda:demo.machine.state in ('FAILED','RECOVERY_REQUIRED'),10)
        assert demo.machine.state=='FAILED' and demo.machine.outcome==outcome,demo.machine.message
        assert demo.machine.stop_confirmed and len(demo.history)==1
        assert not server.reserved and server.active is None
        assert abs(world.v)<1e-9 and abs(world.w)<1e-9
    finally:
        world.frisbee_enabled=True;world.freeze=False
        if demo.machine.busy:
            demo.request_cancel();until(lambda:demo.machine.pending is None,8)


def test_original_follow_waits_through_stationary_period_instead_of_new_progress_abort(round_stack):
    server,world,demo,_=round_stack
    world.owner_x=world.x;world.frisbee_x=world.x+3.
    try:
        time.sleep(.2)
        until(lambda:demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),5)
        assert demo.start_roundtrip()[0]
        until(lambda:server.active is not None and server.active.phase=='ACTIVE',5)
        world.freeze=True
        time.sleep(6.)
        assert demo.machine.state=='APPROACH_FRISBEE' and server.active.p['blocked_policy']=='wait'
        demo.request_cancel()
        until(lambda:demo.machine.pending is None,8)
        assert demo.machine.state=='CANCELED' and demo.machine.stop_confirmed
    finally:
        world.freeze=False
        if demo.machine.busy:
            demo.request_cancel();until(lambda:demo.machine.pending is None,8)


@pytest.mark.parametrize('rear_blocked',[False,True])
def test_original_recovery_passes_zero_forward_nominal_and_checks_rear_space(round_stack,rear_blocked):
    server,world,demo,statuses=round_stack
    decisions=[]
    subscription=world.create_subscription(DiagnosticArray,'/robot_local_motion/planner_decision',
        lambda msg:decisions.append((time.monotonic(),msg.status[0].message)),10)
    world.yaw=0.;world.owner_x=world.x;world.frisbee_x=world.x-3.
    start=time.monotonic()
    try:
        world.freeze=True
        time.sleep(.6)
        until(lambda:demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),5)
        world.fixed_obstacles=[(world.x+.48,world.y)]
        if rear_blocked:world.fixed_obstacles.append((world.x-.48,world.y))
        time.sleep(.2)
        assert demo.start_roundtrip()[0]
        if rear_blocked:
            until(lambda:any(state=='EMERGENCY_REVERSE_BLOCKED' for at,state in decisions if at>=start),5)
            time.sleep(5.5)
            assert demo.machine.state=='APPROACH_FRISBEE'
            assert not any(v<-.01 for at,v,w in world.commands if at>=start)
            world.fixed_obstacles=world.fixed_obstacles[:1]
        until(lambda:any(v<-.05 for at,v,w in world.commands if at>=start),6)
        assert server.active.engine.follow_control is not None
        assert server.active.p['effective_planner']['enable_emergency_reverse']
        assert all(abs(w)<1e-9 for at,v,w in world.commands if at>=start and v<-.01)
        assert any(state=='EMERGENCY_REVERSING' for at,state in decisions if at>=start)
        before=world.x;world.freeze=False
        until(lambda:world.x<before-.03,4)
        demo.request_cancel()
        until(lambda:demo.machine.pending is None,8)
        assert demo.machine.state=='CANCELED' and demo.machine.stop_confirmed
        assert abs(world.v)<1e-9 and abs(world.w)<1e-9
    finally:
        world.fixed_obstacles=[];world.freeze=False
        if demo.machine.busy:
            demo.request_cancel();until(lambda:demo.machine.pending is None,8)
        world.destroy_subscription(subscription)


def test_target_revocation_stops_reverse_without_return_dispatch(round_stack):
    server,world,demo,_=round_stack
    world.yaw=0.;world.owner_x=world.x;world.frisbee_x=world.x-3.
    start=time.monotonic()
    try:
        world.freeze=True;time.sleep(.6)
        until(lambda:demo.stationary(time.monotonic()) and demo.ready_target('0x87654324',time.monotonic()),5)
        world.fixed_obstacles=[(world.x+.48,world.y)];time.sleep(.2)
        assert demo.start_roundtrip()[0]
        until(lambda:any(v<-.05 for at,v,w in world.commands if at>=start),6)
        world.frisbee_enabled=False;lost=time.monotonic()
        until(lambda:abs(world.v)<1e-9 and abs(world.w)<1e-9,1)
        assert all(abs(v)<1e-9 and abs(w)<1e-9 for at,v,w in world.commands if at>=lost+.3)
        until(lambda:demo.machine.pending is None,8)
        assert demo.machine.state=='FAILED' and demo.machine.outcome=='INPUT_LOST'
        assert demo.machine.stop_confirmed and len(demo.history)==1
        assert not server.reserved
    finally:
        world.fixed_obstacles=[];world.freeze=False;world.frisbee_enabled=True
        if demo.machine.busy:
            demo.request_cancel();until(lambda:demo.machine.pending is None,8)


@pytest.mark.parametrize('phase',['ack','feedback'])
def test_disabled_travel_deadline_keeps_communication_and_cancel_settlement_bounded(round_stack,phase):
    probe=UwbRoundTripDemo(cli_args=['--ros-args','-r','__node:=uwb_roundtrip_watchdog_probe'],
        parameter_overrides=[Parameter('owner_id',value='0x87654322'),Parameter('frisbee_id',value='0x87654324'),
                            Parameter('status_topic',value='/test/watchdog/status')])
    try:
        now=time.monotonic();probe.machine.start(now-11)
        probe.request_sent_at=now-11
        assert probe.machine.pending.timeout_sec==0
        if phase=='ack':probe.send_future=Future()
        else:
            probe.goal_handle=SimpleNamespace(cancel_goal_async=lambda:Future())
            probe.result_future=Future();probe.feedback_at=now-11
        probe.poll_motion(now)
        assert probe.machine.cancel_requested and probe.machine.pending is not None
        probe.poll_motion(now+probe.settle_timeout+1)
        assert probe.machine.state=='RECOVERY_REQUIRED' and probe.machine.outcome=='STOP_UNCONFIRMED'
        assert probe.machine.pending is not None
    finally:probe.destroy_node()
