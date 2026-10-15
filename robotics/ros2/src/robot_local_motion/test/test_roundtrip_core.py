import math
import pytest
from local_motion_test_support import Limits, MotionTask, Pose, Target, parse_parameters
from _local_motion_under_test.roundtrip_core import RoundTrip, RoundTripConfig
from _local_motion_under_test.roundtrip_launch import validate_roles, validate_chassis
from _local_motion_under_test.target_guard import TargetPolicy, ArrivalEvidence, target_status, bounded_approach_speed


OWNER, FRISBEE = '0x87654322', '0x87654324'


def machine():
    return RoundTrip(RoundTripConfig(OWNER, FRISBEE))


def strict_task():
    limits = Limits(max_goal_distance=5.0, max_linear_speed=.3)
    params = parse_parameters('{"max_linear_speed":0.3,"distance_deadband_m":0.2,"distance_reengage_m":0.25}', 'approach', limits)
    return MotionTask('approach', params, Pose(0,0), Pose(0,0), 0, limits, TargetPolicy(enabled=True))


def test_wait_is_three_seconds_after_confirmed_stop_and_switches_identity():
    m = machine()
    assert m.start(0).target_id == FRISBEE
    assert m.tick(8, True, True) is None  # goal still owned; elapsed time cannot start dwell
    m.motion_done(10, 'SUCCEEDED', True)
    assert m.state == 'DWELL'
    assert m.tick(12.999, True, True) is None
    request = m.tick(13, True, True)
    assert m.state == 'RETURN_OWNER' and request.target_id == OWNER
    m.motion_done(20, 'SUCCEEDED', True)
    assert m.state == 'DONE' and m.stop_confirmed


@pytest.mark.parametrize('outcome,stopped', [('SUCCEEDED',False), ('INPUT_LOST',True), ('CANCELED',True)])
def test_failed_or_unconfirmed_outbound_never_starts_return(outcome,stopped):
    m=machine();m.start(0);m.motion_done(5,outcome,stopped)
    assert m.tick(30,True,True) is None
    assert m.state in ('FAILED','RECOVERY_REQUIRED')


def test_cancel_during_dwell_does_not_return_and_recovery_is_not_cleared_by_cancel():
    m=machine();m.start(0);m.motion_done(5,'SUCCEEDED',True)
    m.cancel(True)
    assert m.tick(8,True,True) is None and m.state=='CANCELED'
    n=machine();n.start(0);n.motion_done(5,'SUCCEEDED',False);n.cancel(True)
    assert n.state=='RECOVERY_REQUIRED'
    with pytest.raises(ValueError):n.start(9)


def test_cancel_waits_for_pending_child_terminal_result():
    m=machine();m.start(0);m.cancel(False)
    assert m.pending is not None
    assert m.tick(4,True,True) is None
    m.motion_done(5,'CANCELED',True)
    assert m.state=='CANCELED' and m.stop_confirmed


def test_lost_stationary_evidence_during_dwell_blocks_return():
    m=machine();m.start(0);m.motion_done(5,'SUCCEEDED',True)
    assert m.tick(6,False,True) is None
    assert m.state=='RECOVERY_REQUIRED'


def test_owner_search_reuses_turn_and_never_moves_to_an_old_position():
    m=machine();m.start(0);m.motion_done(5,'SUCCEEDED',True)
    assert m.tick(8,True,False) is None
    request=m.tick(8.61,True,False)
    assert request.mode=='turn' and request.yaw_delta==math.pi/2
    m.motion_done(12,'SUCCEEDED',True)
    request=m.tick(12.1,True,True)
    assert request.mode=='approach' and request.target_id==OWNER


def test_owner_search_timeout_is_a_stopped_failure():
    m=machine();m.start(0);m.motion_done(5,'SUCCEEDED',True)
    m.tick(8,True,False)
    assert m.tick(28.1,True,False) is None
    assert m.state=='FAILED' and m.outcome=='INPUT_LOST' and m.stop_confirmed


def test_strict_arrival_requires_distinct_observations_not_control_ticks():
    t=strict_task();sample=Target(1,0,0,sequence=1)
    for tick in (0,.1,.2,.3,.4):
        assert not t.tick(tick,Pose(0,0),sample).outcome
    for i in range(2,7):
        now=i*.1
        result=t.tick(now,Pose(0,0),Target(1,0,now,sequence=i))
    assert result.outcome=='SUCCEEDED'


@pytest.mark.parametrize('distance', [.499, .599])
def test_strict_arrival_resets_on_loss_and_accepts_closer_target(distance):
    t=strict_task();t.tick(0,Pose(0,0),Target(1,0,0,sequence=1))
    t.tick(.1,Pose(0,0),None)
    assert not t.tick(.2,Pose(0,0),Target(1,0,.2,sequence=2)).outcome
    for sequence in range(3,9):
        now=sequence*.1
        result=t.tick(now,Pose(0,0),Target(distance,0,now,sequence=sequence))
        assert result.linear==0 and result.state=='HOLDING'
        assert result.outcome in ('', 'SUCCEEDED')
    assert result.outcome=='SUCCEEDED'


def test_five_meter_slow_target_and_moving_owner_progress():
    t=strict_task()
    for i in range(80):
        now=i*.1;pose=Pose(i*.03,0)
        # Owner travels at the robot's speed. Range is constant; own progress is real.
        result=t.tick(now,pose,Target(pose.x+4,0,now,sequence=i+1),linear_velocity=.3)
        assert not result.outcome
    assert strict_task().tick(0,Pose(0,0),Target(5,0,0,sequence=1)).outcome==''
    assert strict_task().tick(0,Pose(0,0),Target(5.1,0,0,sequence=1)).outcome=='TARGET_OUT_OF_RANGE'


def test_target_braking_does_not_force_minimum_speed_through_boundary():
    policy=TargetPolicy(enabled=True)
    assert bounded_approach_speed(.3,.3,1.1,1,.25,policy)==0
    assert 0 < bounded_approach_speed(.3,.3,3,1,.25,policy) <= .3
    # The requested 1 m standoff has a 0.2 m arrival band. Its lower edge
    # remains protected while minimum executable speed can reach the band.
    assert bounded_approach_speed(.25,0,1.21,.8,.25,policy)==.25


def test_requested_roundtrip_limits_accept_one_meter_per_second_and_ten_meters():
    limits=Limits(max_linear_speed=1.0,max_angular_speed=1.2,max_goal_distance=10.0)
    request='{"max_linear_speed":1.0,"max_angular_speed":1.2}'
    params=parse_parameters(request,'approach',limits)
    task=MotionTask('approach',params,Pose(0,0),Pose(0,0),0,limits,TargetPolicy(enabled=True))
    assert task.tick(0,Pose(0,0),Target(10,0,0,sequence=1)).linear==1.0
    assert task.tick(.1,Pose(0,0),Target(10.01,0,.1,sequence=2)).outcome=='TARGET_OUT_OF_RANGE'
    for excessive in ('{"max_linear_speed":1.01}', '{"max_linear_speed":1.0,"max_angular_speed":1.21}'):
        with pytest.raises(ValueError):parse_parameters(excessive,'approach',limits)
    # Wider opt-in task support does not raise the original deployment defaults.
    with pytest.raises(ValueError):parse_parameters(request,'approach')


def test_turning_towards_owner_behind_robot_is_real_progress():
    t=strict_task()
    for i in range(75):
        now=i*.1
        result=t.tick(now,Pose(0,0,min(math.pi,now*.6)),Target(-4,0,now,sequence=i+1))
        assert not result.outcome


@pytest.mark.parametrize('distance', [.499, .599])
def test_post_stop_target_status_accepts_closer_target_and_detects_move_loss(distance):
    t=strict_task();p=t.p;l=t.limits
    assert target_status(Pose(0,0),Target(1,0,1),1,p,l)[0]=='HOLDING'
    assert target_status(Pose(0,0),Target(1.4,0,1),1,p,l)[0]=='MOVING'
    assert target_status(Pose(0,0),Target(distance,0,1),1,p,l)[0]=='HOLDING'
    assert target_status(Pose(0,0),Target(1,0,0),1,p,l)[0]=='INPUT_LOST'


def test_roles_must_be_explicit_distinct_and_verified():
    assert validate_roles(OWNER,FRISBEE)==(OWNER,FRISBEE)
    assert validate_roles(FRISBEE,OWNER)==(FRISBEE,OWNER)
    for pair in [('',FRISBEE),(OWNER,OWNER),(OWNER,'0x1')]:
        with pytest.raises(ValueError):validate_roles(*pair)


def test_chassis_file_requires_consistent_values_and_cannot_replace_motion_gates():
    doc={'local_motion_server':{'ros__parameters':{'min_linear_speed':.2,'target_braking_decel':.5}},
         'local_velocity_planner_node':{'ros__parameters':{'min_linear_speed':.2,'max_linear_decel':.5}}}
    assert validate_chassis(doc)==(.2,.5)
    doc['local_motion_server']['ros__parameters']['strict_target_arrival']=False
    with pytest.raises(ValueError):validate_chassis(doc)


@pytest.mark.parametrize('mode', ['move','approach','follow','orbit','explore','turn'])
def test_zero_timeout_is_rejected_by_ordinary_deployment(mode):
    with pytest.raises(ValueError):parse_parameters('{"timeout_sec":0}',mode)


@pytest.mark.parametrize('mode', ['move','follow','orbit','explore','turn'])
def test_unbounded_permission_does_not_disable_other_motion_deadlines(mode):
    with pytest.raises(ValueError):
        parse_parameters('{"timeout_sec":0}',mode,allow_unbounded_approach=True)


def unbounded_approach():
    import json
    limits=Limits(max_linear_speed=1.0,min_linear_speed=.1,max_goal_distance=10.0)
    params=parse_parameters(json.dumps({'timeout_sec':0.0,'max_linear_speed':.3,
        'desired_distance_m':.5,'distance_deadband_m':.2,'distance_reengage_m':.25}),
        'approach',limits,allow_unbounded_approach=True)
    return MotionTask('approach',params,Pose(0,0),Pose(0,0),0,limits,TargetPolicy(enabled=True))


def test_unbounded_approach_keeps_progress_and_can_finish_after_sixty_seconds():
    t=unbounded_approach()
    for i in range(701):
        now=i*.1;pose=Pose(i*.03,0)
        result=t.tick(now,pose,Target(pose.x+3,0,now,sequence=i+1),linear_velocity=.3)
        assert not result.outcome
    for i in range(6):
        now=70.1+i*.1
        result=t.tick(now,pose,Target(pose.x+.6,0,now,sequence=702+i),linear_velocity=0)
    assert result.outcome=='SUCCEEDED'
    # Zero is a disabled deadline, not a replacement one-hour time budget.
    t=unbounded_approach()
    assert not t.tick(7200,Pose(0,0),Target(3,0,7200,sequence=1)).outcome


@pytest.mark.parametrize('fault,outcome', [('target_loss','INPUT_LOST'),('no_progress','NO_PROGRESS'),('blocked','BLOCKED')])
def test_unbounded_approach_keeps_loss_progress_and_blocked_guards(fault,outcome):
    t=unbounded_approach()
    t.tick(0,Pose(0,0),Target(3,0,0,sequence=1))
    if fault=='target_loss':
        t.tick(.1,Pose(0,0),None)
        result=t.tick(3.2,Pose(0,0),None)
    elif fault=='no_progress':
        result=t.tick(5.1,Pose(0,0),Target(3,0,5.1,sequence=2))
    else:
        t.tick(.1,Pose(0,0),Target(3,0,.1,sequence=2),blocked=True)
        result=t.tick(3.2,Pose(0,0),Target(3,0,3.2,sequence=3),blocked=True)
    assert result.outcome==outcome and result.linear==0


def test_explicit_positive_deadline_and_roundtrip_search_budget_remain_bounded():
    limits=Limits(max_linear_speed=1.0,min_linear_speed=.1,max_goal_distance=10.0)
    params=parse_parameters('{"timeout_sec":30}', 'approach',limits,allow_unbounded_approach=True)
    t=MotionTask('approach',params,Pose(0,0),Pose(0,0),0,limits,TargetPolicy(enabled=True))
    assert t.tick(31,Pose(0,0),Target(3,0,31,sequence=1)).outcome=='TIMEOUT'
    m=machine();request=m.start(0)
    assert request.timeout_sec==0
    m.motion_done(40,'SUCCEEDED',True)
    request=m.tick(43,True,True)
    assert request.target_id==OWNER and request.timeout_sec==0
    bounded=RoundTrip(RoundTripConfig(OWNER,FRISBEE,approach_timeout_sec=30))
    assert bounded.start(0).timeout_sec==30


@pytest.mark.parametrize('budget',[-1,float('nan'),float('inf'),True])
def test_roundtrip_rejects_invalid_approach_budget(budget):
    with pytest.raises(ValueError):RoundTripConfig(OWNER,FRISBEE,approach_timeout_sec=budget)


def test_parameter_schema_records_zero_timeout_deployment_exception():
    import json
    from pathlib import Path
    from _local_motion_under_test.core import parameter_schema
    saved=json.loads((Path(__file__).resolve().parents[1]/'config/parameter_schema.json').read_text())
    assert saved==json.loads(json.dumps(parameter_schema()))
    assert saved['numeric']['timeout_sec']['min']==.1
    assert saved['deployment_exceptions']['timeout_sec']['requires']=='allow_unbounded_approach'
