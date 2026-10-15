"""Exercise the actual existing C++ follow core and the recovery output contract."""
import math
from types import SimpleNamespace
import pytest
import local_motion_test_support  # Source implementation without shadowing ROS IDL.
from _local_motion_under_test.uwb_follow_backend import UwbFollowControl, load_follow_profile
from _local_motion_under_test.core import Limits, MotionTask, Pose, Target, parse_parameters
from _local_motion_under_test.target_guard import TargetPolicy
from robot_local_motion_runtime.server import LocalMotionServer


def controller(distance=.5):
    return UwbFollowControl(load_follow_profile(), distance, .1, 1., 1.2)


def test_same_original_follow_profile_only_distance_and_chassis_caps_change():
    profile=load_follow_profile()
    frisbee=controller(.5);owner=controller(1.)
    try:
        assert frisbee.command(.75,0,0)[0]>.1
        assert owner.command(.75,0,0)[0]==0
        changed={'follow_distance','min_linear_speed','max_linear_speed','max_angular_speed','blind_rotation_max_speed'}
        assert all(frisbee.config[k]==v for k,v in profile.items() if k not in changed)
        assert frisbee.config['turn_response_delay']==profile['turn_response_delay']
        assert frisbee.lib._name.endswith('libuwb_follow_binding.so')
    finally:frisbee.close();owner.close()


def test_original_rear_target_direction_survives_pi_wrap():
    follow=controller()
    try:
        v,w=follow.command(-3.,-.01,0.)
        assert v==0 and w<0
        v,w=follow.command(-3.,.01,0.)
        assert v==0 and w<0
        follow.reset()
        assert follow.command(-3.,.01,0.)[1]>0
    finally:follow.close()


def test_original_dynamic_brake_latches_until_actual_turn_is_stopped():
    follow=controller()
    point=lambda heading:(3*math.cos(heading),3*math.sin(heading))
    try:
        assert follow.command(*point(1.2),.7)[1]>0
        assert follow.command(*point(.25),.7)[1]==0
        assert follow.command(*point(1.2),.3)[1]==0
        assert follow.command(*point(1.2),0.)[1]>0
    finally:follow.close()


def test_arrival_observer_accepts_original_planner_angular_stopping_band():
    import json
    follow=controller()
    settings=parse_parameters(json.dumps({'desired_distance_m':.5,'distance_deadband_m':.2,
        'distance_reengage_m':.25,'yaw_tolerance_rad':.160000001}), 'approach')
    task=MotionTask('approach',settings,Pose(0,0),Pose(0,0),0,
        Limits(min_linear_speed=.1),TargetPolicy(enabled=True),follow)
    try:
        # The original core requests 0.07 rad/s here; the old planner's 0.08
        # command deadband has already stopped it. This must not stall completion.
        assert 0 < follow.command(.65*math.cos(.15),.65*math.sin(.15),0)[1] < .08
        for i in range(7):
            now=i*.1
            step=task.tick(now,Pose(0,0),Target(.65*math.cos(.15),.65*math.sin(.15),now,sequence=i+1))
        assert step.outcome=='SUCCEEDED' and step.angular==0
    finally:follow.close()


@pytest.mark.parametrize('point',[(math.nan,0,0),(0,math.inf,0),(0,0,math.nan)])
def test_nonfinite_inputs_do_not_reach_native_control(point):
    follow=controller()
    try:
        with pytest.raises(ValueError):follow.command(*point)
    finally:follow.close()


def recovery_case():
    task=SimpleNamespace(engine=SimpleNamespace(follow_control=object()),
        p={'effective_planner':{'enable_emergency_reverse':True},'max_linear_speed':1.},reverse_limit=.3)
    row={'state':'EMERGENCY_REVERSING','recovery':True,'enabled':True,'final':(-.3,0.),'maximum':.3}
    server=SimpleNamespace(final_ns=123,decisions={123:row})
    return server,task,row


def test_confirmed_same_command_recovery_can_pass_zero_nominal_linear():
    server,task,_=recovery_case()
    assert LocalMotionServer.reverse_allowed(server,task,(-.3,0.))


@pytest.mark.parametrize('fault',['stamp','state','inactive','disabled','different_velocity',
    'rotating','too_fast','not_native','task_disabled'])
def test_unproven_or_out_of_bounds_reverse_is_rejected(fault):
    server,task,row=recovery_case();output=(-.3,0.)
    if fault=='stamp':server.final_ns=124
    elif fault=='state':row['state']='PLANNING'
    elif fault=='inactive':row['recovery']=False
    elif fault=='disabled':row['enabled']=False
    elif fault=='different_velocity':row['final']=(-.2,0.)
    elif fault=='rotating':row['final']=output=(-.3,.1)
    elif fault=='too_fast':row['final']=output=(-.4,0.)
    elif fault=='not_native':task.engine.follow_control=None
    elif fault=='task_disabled':task.p['effective_planner']['enable_emergency_reverse']=False
    assert not LocalMotionServer.reverse_allowed(server,task,output)
