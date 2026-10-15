"""CPU/DDS tests with synthetic sensors and an isolated actuator topic.

Run after build, with the new overlay sourced. No camera, UWB device, chassis or
production ROS domain is used. This verifies the real planner/task lifecycle.
"""
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
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rcl_interfaces.srv import GetParameters, SetParametersAtomically
from rclpy.parameter import Parameter
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header
from tf2_ros import TransformBroadcaster
from robot_local_motion.action import ExecuteLocalMotion
from robot_local_motion.msg import TargetObservation
from robot_local_motion.srv import ReleaseRecovery
from robot_local_motion_runtime.server import LocalMotionServer


def wait(future, timeout=15):
    end=time.monotonic()+timeout
    while not future.done() and time.monotonic()<end:
        time.sleep(.02)
    assert future.done(), 'DDS future did not settle'
    return future.result()


def stop_owned_planner(process):
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=5)
    # ros2 run may exit before its executable; reap only this test's process group.
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass


class World(Node):
    def __init__(self):
        super().__init__('local_motion_test_world')
        from sensor_msgs.msg import PointCloud2
        from rclpy.qos import qos_profile_sensor_data
        self.odom=self.create_publisher(Odometry,'/test/odom',qos_profile_sensor_data)
        self.cloud=self.create_publisher(PointCloud2,'/test/cloud',qos_profile_sensor_data)
        self.target=self.create_publisher(TargetObservation,'/robot_local_motion/target',10)
        self.tf=TransformBroadcaster(self)
        self.sub=self.create_subscription(Twist,'/test/cmd_vel',self.command,10)
        self.x=self.y=self.yaw=self.v=self.w=0.0
        self.odom_child_frame='base_footprint';self.tf_child_frame='base_footprint';self.body_height=0.0
        self.freeze=False;self.inputs=True;self.targets=False;self.sequence=0;self.direct=True
        self.commands=[];self.last=time.monotonic()
        self.timer=self.create_timer(.02,self.tick)
    def cloud_data(self):
        return []
    def command(self,msg):
        if self.direct:
            self.v,self.w=msg.linear.x,msg.angular.z
        self.commands.append((time.monotonic(),self.v,self.w))
    def tick(self):
        now=time.monotonic();dt=now-self.last;self.last=now
        if not self.freeze:
            self.x+=self.v*math.cos(self.yaw)*dt
            self.y+=self.v*math.sin(self.yaw)*dt
            self.yaw+=self.w*dt
        if not self.inputs:return
        stamp=self.get_clock().now().to_msg()
        odom=Odometry();odom.header=Header(stamp=stamp,frame_id='odom');odom.child_frame_id=self.odom_child_frame
        odom.pose.pose.position.x=self.x;odom.pose.pose.position.y=self.y
        odom.pose.pose.position.z=self.body_height
        odom.pose.pose.orientation.z=math.sin(self.yaw/2);odom.pose.pose.orientation.w=math.cos(self.yaw/2)
        odom.twist.twist.linear.x=self.v if not self.freeze else 0.0
        odom.twist.twist.angular.z=self.w if not self.freeze else 0.0
        self.odom.publish(odom)
        tf=TransformStamped();tf.header=odom.header;tf.child_frame_id=self.tf_child_frame
        tf.transform.translation.x=self.x;tf.transform.translation.y=self.y
        tf.transform.rotation=odom.pose.pose.orientation;self.tf.sendTransform(tf)
        delayed=rclpy.time.Time(nanoseconds=self.get_clock().now().nanoseconds-50000000).to_msg()
        self.cloud.publish(point_cloud2.create_cloud_xyz32(Header(stamp=delayed,frame_id='base_footprint'),self.cloud_data()))
        if self.targets:
            self.sequence+=1
            msg=TargetObservation();msg.header=Header(stamp=stamp,frame_id='odom')
            msg.position.x=self.x+1.2;msg.position.y=self.y
            msg.target_id='owner';msg.source='test';msg.sequence=self.sequence;msg.valid=True;msg.confidence=1.0
            self.target.publish(msg)


@pytest.fixture(scope='module')
def stack(tmp_path_factory):
    assert os.environ.get('ROS_LOCALHOST_ONLY')=='1'
    assert os.environ.get('ROS_DOMAIN_ID') in ('219','220'), 'explicit isolated test domain required'
    directory=tmp_path_factory.mktemp('local-motion-dds')
    log=(directory/'planner.log').open('w')
    share=__import__('ament_index_python.packages',fromlist=['get_package_share_directory']).get_package_share_directory
    args=['ros2','run','go2_uwb_local_follow','local_velocity_planner_node','--ros-args',
          '--params-file',str(Path(share('go2_uwb_local_follow'))/'config/local_velocity_planner.yaml')]
    params={'enable_motion':'true','enable_task_parameters':'true','odom_topic':'/test/odom',
      'obstacle_topic':'/test/cloud','nominal_cmd_topic':'/robot_local_motion/nominal_cmd',
      'final_cmd_topic':'/robot_local_motion/final_cmd','cmd_vel_topic':'/test/planner_raw',
      'diagnostics_topic':'/robot_local_motion/planner_diagnostics'}
    for k,v in params.items():args+=['-p',f'{k}:={v}']
    planner=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    rclpy.init(args=['--ros-args','-p','enable_motion:=true','-p','odom_topic:=/test/odom',
        '-p','obstacle_topic:=/test/cloud','-p','cmd_vel_topic:=/test/cmd_vel','-p','stop_timeout_sec:=0.8'])
    server=LocalMotionServer();world=World()
    executor=MultiThreadedExecutor(num_threads=4);executor.add_node(server);executor.add_node(world)
    thread=threading.Thread(target=executor.spin);thread.start()
    client=ActionClient(world,ExecuteLocalMotion,'/robot_local_motion/execute')
    try:
        assert client.wait_for_server(timeout_sec=5)
        time.sleep(1)
        yield server,world,client
    finally:
        stop_owned_planner(planner)
        executor.shutdown();thread.join(timeout=5)
        world.destroy_node();server.destroy_node();rclpy.shutdown();log.close()


def send(client,mode='move',parameters=None,x=.6):
    goal=ExecuteLocalMotion.Goal();goal.mode=mode
    goal.goal.header.frame_id='base_footprint';goal.goal.pose.position.x=x;goal.goal.pose.orientation.w=1.0
    goal.target_id='owner';goal.target_source='test'
    goal.parameters_json=json.dumps({'timeout_sec':12.0,**(parameters or {})})
    handle=wait(client.send_goal_async(goal),5)
    assert handle.accepted
    return handle


def test_move_uses_real_mppi_with_task_cap_and_confirms_stop(stack):
    server,world,client=stack
    start=world.x;offset=len(world.commands)
    handle=send(client,parameters={'max_linear_speed':.3,'planner':{'weight_obstacle':3.0}})
    wrapped=wait(handle.get_result_async())
    assert wrapped.status==4 and wrapped.result.outcome=='SUCCEEDED', wrapped.result
    assert wrapped.result.stop_confirmed
    assert .4 <= world.x-start <= .75
    assert any(v>.0 for _,v,_ in world.commands[offset:])
    assert all(abs(v)<=.3+1e-6 for _,v,_ in world.commands[offset:])
    assert json.loads(wrapped.result.effective_parameters_json)['effective_planner']['weight_obstacle']==3.0


def test_cancel_settles_and_next_task_resets_planner_parameters(stack):
    server,world,client=stack;world.targets=True
    # A newly restarted task owner loses its cache while the planner still
    # holds last task's overrides. The planner startup snapshot must win.
    server.baseline=None
    handle=send(client,'follow',{'desired_distance_m':1.0,'max_linear_speed':.4})
    time.sleep(1.5)
    wait(handle.cancel_goal_async())
    wrapped=wait(handle.get_result_async(),5)
    assert wrapped.result.outcome=='CANCELED' and wrapped.result.stop_confirmed
    assert not server.reserved
    assert server.active is None
    world.targets=False
    handle=send(client,parameters={'max_linear_speed':.3})
    wrapped=wait(handle.get_result_async())
    assert wrapped.result.outcome=='SUCCEEDED'
    effective=json.loads(wrapped.result.effective_parameters_json)['effective_planner']
    assert effective['weight_obstacle']==2.0  # restored original Lite3 profile, not last task's 3.0


def test_unrelated_target_cannot_satisfy_approach(stack):
    server,world,client=stack
    observation=TargetObservation()
    observation.header=Header(stamp=world.get_clock().now().to_msg(),frame_id='odom')
    observation.position.x=world.x+.7;observation.position.y=world.y
    observation.target_id='intruder';observation.source='test';observation.sequence=1
    observation.confidence=1.0;observation.valid=True
    world.target.publish(observation)
    handle=send(client,'approach',{'lost_target_policy':'abort'})
    wrapped=wait(handle.get_result_async(),6)
    assert wrapped.result.outcome=='INPUT_LOST' and wrapped.result.stop_confirmed


def test_sensor_loss_keeps_recovery_lock_until_fresh_stationary_input(stack):
    server,world,client=stack
    handle=send(client,x=1.5)
    time.sleep(1.0);world.inputs=False;world.freeze=True
    wait(handle.cancel_goal_async())
    wrapped=wait(handle.get_result_async(),5)
    assert wrapped.result.outcome=='STOP_UNCONFIRMED' and not wrapped.result.stop_confirmed
    assert server.recovery_locked
    request=ExecuteLocalMotion.Goal();request.mode='move';request.goal.header.frame_id='base_footprint';request.goal.pose.orientation.w=1.0
    assert not wait(client.send_goal_async(request),3).accepted
    service=world.create_client(ReleaseRecovery,'/robot_local_motion/release_recovery')
    assert service.wait_for_service(timeout_sec=2)
    assert not wait(service.call_async(ReleaseRecovery.Request(confirm_release=True)),3).released
    world.inputs=True;time.sleep(1.0)
    assert wait(service.call_async(ReleaseRecovery.Request(confirm_release=True)),3).released
    assert not server.recovery_locked


def test_planner_rejects_weaker_deployment_limit_atomically(stack):
    _,world,_=stack
    service=world.create_client(SetParametersAtomically,'/local_velocity_planner_node/set_parameters_atomically')
    assert service.wait_for_service(timeout_sec=2)
    request=SetParametersAtomically.Request(parameters=[Parameter('max_linear_speed',value=.4).to_parameter_msg(),
                                                       Parameter('minimum_safe_clearance',value=.001).to_parameter_msg()])
    result=wait(service.call_async(request),3)
    assert not result.result.successful
    getter=world.create_client(GetParameters,'/local_velocity_planner_node/get_parameters')
    assert getter.wait_for_service(timeout_sec=2)
    before=wait(getter.call_async(GetParameters.Request(names=['max_linear_speed'])),3)
    assert before.values[0].double_value==.5  # last move default; failed transaction made no partial update


@pytest.mark.parametrize('mode',['move','approach'])
def test_ordinary_server_rejects_disabled_task_deadline(stack,mode):
    server,world,client=stack
    assert not server.allow_unbounded_approach
    goal=ExecuteLocalMotion.Goal();goal.mode=mode
    goal.goal.header.frame_id='base_footprint';goal.goal.pose.orientation.w=1.0
    goal.target_id='owner';goal.target_source='test';goal.parameters_json='{"timeout_sec":0}'
    handle=wait(client.send_goal_async(goal),3)
    assert not handle.accepted and not server.reserved
