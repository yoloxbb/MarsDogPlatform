import math
import pytest
from uwb_test_support import BeaconTracker, TrackingConfig, ObservationOrder, frame


def tracker(**settings):
    return BeaconTracker(TrackingConfig(acquire_samples=1, **settings))


def test_independent_histories_expiry_and_replay_watermarks():
    a, b = tracker(), tracker()
    assert a.update(frame(sync=100, distance=2), 0).valid
    assert b.update(frame(identity=0x87654324, sync=50, distance=8), 0).valid
    assert a.update(frame(sync=101, distance=8), .1).reason == 'jump_rejected'
    assert b.update(frame(identity=0x87654324, sync=51, distance=8), .1).valid
    assert a.filtered[0] == 2 and b.filtered[0] == 8
    assert a.update(frame(sync=100), .2) is None
    assert a.expire(.81).reason == 'expired'
    assert b.expire(.79) is None
    assert a.update(frame(sync=101), .9) is None
    assert a.update(frame(sync=102, distance=3), 1).valid


def test_wrapped_angle_does_not_cause_false_position_jump_and_sync_wrap():
    t = tracker(smoothing_tau_sec=0)
    assert t.update(frame(sync=0xffffffff, angle=179), 0).valid
    assert t.update(frame(sync=0, angle=-179), .1).valid
    assert t.filtered[0] < -1.99


def test_nonfinite_geometry_invalidates_and_good_sample_recovers():
    t = tracker()
    t.update(frame(), 0)
    assert not t.update(frame(sync=2, distance=math.nan), .1).valid
    assert t.update(frame(sync=3), .2).valid
    assert not t.update(frame(sync=4, angle=math.inf), .3).valid


def test_large_jump_is_not_accepted_as_elapsed_time_grows():
    t = tracker()
    t.update(frame(distance=1), 0)
    for i in range(2, 50):
        assert not t.update(frame(sync=i, distance=10), i * .1).valid
    assert t.filtered == (1.0, 0.0)


def test_reacquisition_is_explicit_and_requires_cluster():
    t = tracker(allow_jump_reacquire=True, reacquire_samples=3)
    t.update(frame(distance=1), 0)
    assert not t.update(frame(sync=2, distance=3), .1).valid
    assert not t.update(frame(sync=3, distance=6), .2).valid
    assert not t.update(frame(sync=4, distance=6.05), .3).valid
    assert t.update(frame(sync=5, distance=6), .4).reason == 'reacquired'


def test_beacon_power_reset_requires_staleness_and_several_advancing_samples():
    t=tracker()
    t.update(frame(sync=100),0)
    assert t.update(frame(sync=1),.1) is None
    assert t.expire(.8).reason=='expired'
    assert t.update(frame(sync=1),.9) is None
    assert t.update(frame(sync=1),1.0) is None
    assert t.update(frame(sync=2),1.1) is None
    assert t.update(frame(sync=3),1.2).valid
    assert t.counters['wire_clock_reset']==1


def test_ordered_invalidation_can_reuse_stamp_without_clearing_newer_target():
    order = ObservationOrder()
    a, b = ('uwb', 'a'), ('uwb', 'b')
    assert order.accept(a, 10, 900, 1000, True)
    assert order.accept(b, 10, 850, 1000, True)
    assert not order.accept(a, 9, 900, 1000, False)
    assert not order.accept(a, 11, 800, 1000, False)
    assert order.accept(a, 11, 900, 1000, False)
    assert not order.accept(a, 12, 900, 1000, True)
    assert order.accept(a, 12, 950, 1000, True)
    assert order.stamps[b] == 850
    assert not order.accept(a, 13, 1100, 1000, False)


@pytest.mark.parametrize('settings', [{'max_speed_mps':math.nan}, {'stale_timeout_sec':0},
    {'acquire_samples':True}, {'min_range_m':31}, {'allow_jump_reacquire':'true'}])
def test_invalid_filter_configuration(settings):
    with pytest.raises(ValueError):TrackingConfig(**settings)
