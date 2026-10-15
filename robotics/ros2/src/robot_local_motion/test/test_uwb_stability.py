import local_motion_test_support
from _local_motion_under_test.uwb_stability import analyze_xy


def test_gap_and_connected_jump_are_reported_separately():
    result=analyze_xy([{'t':0,'x':0,'y':0},{'t':.1,'x':1,'y':0},
                       {'t':2,'x':4,'y':0},{'t':2.1,'x':4.01,'y':0}])
    assert result['connected_jumps_over_threshold']==1
    assert result['gaps_over_limit']==1
    assert result['adjacent_step_m']['max']==3
    assert result['connected_step_m']['max']==1
