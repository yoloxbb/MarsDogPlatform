import json
import math
import pytest
from local_motion_test_support import Limits, MotionTask, Pose, Target, parse_parameters


def task(mode='move', settings=None, initial=Pose(0, 0), goal=Pose(1, 0)):
    p = parse_parameters(json.dumps(settings or {}), mode)
    return MotionTask(mode, p, initial, goal, 0)


@pytest.mark.parametrize('raw', ['{"speed":1}', '{"max_linear_speed":true}',
    '{"timeout_sec":NaN}', '{"schema_version":true}', '{"timeout_sec":1,"timeout_sec":2}',
    '{"planner":{"unknown":1}}', '{"planner":{"mppi_batch_size":8.5}}'])
def test_reject_bad_parameters(raw):
    with pytest.raises(ValueError):
        parse_parameters(raw, 'move')


@pytest.mark.parametrize('settings,mode', [({'max_linear_speed':0.1}, 'move'),
    ({'duration_sec':2}, 'move'), ({'desired_distance_m':0.4}, 'approach'),
    ({'min_radius_m':2,'max_radius_m':1}, 'explore'),
    ({'boundary_radius_m':1,'max_radius_m':1}, 'explore'),
    ({'blocked_policy':'resample'}, 'follow')])
def test_reject_incompatible_settings(settings, mode):
    with pytest.raises(ValueError):
        parse_parameters(json.dumps(settings), mode)


def test_goal_is_fixed_and_speed_bounded():
    t = task(settings={'max_linear_speed':0.3})
    assert t.tick(0, Pose(0,0)).linear <= 0.3
    assert t.tick(1, Pose(0.9,0)).linear == 0
    assert t.tick(1.5, Pose(0.9,0)).outcome == 'SUCCEEDED'
    assert t.goal.x == 1
    with pytest.raises(ValueError):
        task(goal=Pose(4,0))


def test_final_yaw_does_not_complete_at_position():
    t = task(settings={'require_final_yaw':True}, goal=Pose(0,0,1))
    assert t.tick(1, Pose(0,0)).state == 'ALIGNING'
    assert not t.tick(2, Pose(0,0)).outcome
    assert not t.tick(3, Pose(0,0,1)).outcome
    assert t.tick(3.5, Pose(0,0,1)).outcome == 'SUCCEEDED'


def test_follow_hysteresis_and_approach_distance():
    t = task('follow')
    assert t.tick(0,Pose(0,0),Target(1.05,0,0)).state == 'HOLDING'
    assert t.tick(1,Pose(0,0),Target(1.1,0,1)).linear == 0
    assert t.tick(2,Pose(0,0),Target(1.3,0,2)).linear > 0
    assert not t.tick(3,Pose(0,0),Target(0.5,0,3)).outcome
    t = task('approach', {'desired_distance_m':0.7})
    assert t.tick(0,Pose(0,0),Target(0.7,0,0)).linear == 0
    assert t.tick(.5,Pose(0,0),Target(.7,0,.5)).outcome == 'SUCCEEDED'


def test_target_loss_invalidates_arrival_hold_and_stops():
    t = task('approach')
    assert not t.tick(0,Pose(0,0),Target(1,0,0)).outcome
    assert t.tick(1,Pose(0,0),None).state == 'TARGET_LOST'
    assert not t.tick(1.1,Pose(0,0),Target(1,0,1.1)).outcome
    assert t.tick(5,Pose(0,0),None).linear == 0
    assert t.tick(8.1,Pose(0,0),None).outcome == 'INPUT_LOST'


def test_duration_timeout_and_no_progress_are_distinct():
    assert task().tick(61, Pose(0,0)).outcome == 'TIMEOUT'
    t = task()
    t.tick(0,Pose(0,0))
    assert t.tick(6,Pose(0,0)).outcome == 'NO_PROGRESS'
    assert task('follow', {'duration_sec':5}).tick(6, Pose(0,0),Target(1,0,6)).outcome == 'SUCCEEDED'


def test_exploration_determinism_sector_and_obstacle_clearance():
    config={'random_seed':7,'sector_width_rad':0.1,'goal_count':2,'goal_pause_sec':1}
    a, b = task('explore',config), task('explore',config)
    a.tick(0,Pose(0,0)); b.tick(0,Pose(0,0))
    assert a.explore_goal == b.explore_goal
    assert abs(math.atan2(a.explore_goal.y,a.explore_goal.x)) <= .05
    a.tick(1,a.explore_goal)
    assert not a.tick(1.5,a.explore_goal).outcome
    assert a.tick(1.6,a.last_pose).state == 'DWELLING'
    dense=[(x/10,y/10) for x in range(-30,31) for y in range(-30,31)]
    assert task('explore').tick(0,Pose(0,0),obstacles=dense).outcome == 'NO_VALID_GOAL'


def test_boundary_blocks_outward_arc_and_allows_recovery():
    t=task(settings={'boundary_radius_m':1})
    assert not t.boundary_allows(Pose(.55,0),.25,0)
    assert t.boundary_allows(Pose(.7,0,math.pi),.25,0)
    assert t.boundary_allows(Pose(.5,0),0,1)


def test_orbit_counts_motion_and_does_not_count_target_movement():
    t=task('orbit',{'orbit_turns':.1,'orbit_radius_m':1,'orbit_capture_tolerance_m':.2})
    t.tick(0,Pose(1,0),Target(0,0,0))
    assert t.tick(1,Pose(1,0),Target(.1,0,1)).progress == 0
    t.tick(2,Pose(math.cos(.7),math.sin(.7)),Target(0,0,2))
    assert t.tick(2.5,t.last_pose,Target(0,0,2.5)).outcome == 'SUCCEEDED'
