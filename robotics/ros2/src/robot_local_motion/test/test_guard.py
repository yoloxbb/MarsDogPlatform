from local_motion_test_support import Pose, StampGuard, StopCheck


def test_replay_stale_future_and_unstamped_are_rejected():
    g=StampGuard()
    assert not g.accept('odom',0,1000000000,.1)
    assert g.accept('odom',950000000,1000000000,.1)
    assert not g.accept('odom',950000000,1000000000,.1)
    assert not g.accept('odom',1000000001,1000000000,.1)
    assert not g.accept('target',500000000,1000000000,.1)


def test_stop_needs_fresh_twist_and_pose_stationarity():
    s=StopCheck()
    assert not s.update(0,Pose(0,0),0,0,True)
    assert not s.update(.5,Pose(.03,0),0,0,True)
    assert not s.update(1,Pose(.03,0),0,0,False)
    assert not s.update(2,Pose(.03,0),.2,0,True)
    assert not s.update(3,Pose(.03,0),0,0,True)
    assert s.update(3.5,Pose(.03,0),0,0,True)
