import copy
import threading
import time
from types import SimpleNamespace
import pytest

from marsdog_action_executor.approach_request import request_for, route_for, validate_plan
from marsdog_action_executor.adapters.geometry_approach_transport import geometry_request, GeometryApproachTransport
from marsdog_action_executor.adapters.person_nav_approach_adapter import PersonNavApproachAdapter
from tests.test_person_nav_approach_adapter import context, Transport, TARGET_ID, POSE, PERSON_POINT

UNIT = 'ACT_INTERACT_APPROACH_VOICE_CALLER'
PAYLOAD = {'ok': True, 'target_id': TARGET_ID, 'coordinate_space': 'original_image_pixels',
    'image_header': {'stamp': 123.25, 'frame_id': 'camera_optical'}, 'image_width': 640, 'image_height': 480,
    'bbox': {'x_offset': 128, 'y_offset': 48, 'width': 256, 'height': 384}}


def test_three_modes_are_explicit_and_legacy_route_is_not_a_fallback():
    assert route_for({'unit_id': UNIT, 'mode': 'visual'}) == 'target_approach'
    assert route_for({'unit_id': UNIT, 'mode': 'local_nav'}) == 'approach_navigation'
    assert route_for({'unit_id': UNIT, 'mode': 'map_nav'}) == 'approach_navigation'
    for raw in [None, {}, {'mode': 'auto', 'unit_id': UNIT}, {'mode': 'map_nav', 'unit_id': 'unknown'}]:
        with pytest.raises((ValueError, TypeError)):
            request_for(raw)


def test_plan_rejects_missing_backend_conflicting_override_and_absent_unit():
    params = {'approach': {'mode': 'map_nav', 'unit_id': UNIT}}
    stages = [{'candidates': [UNIT]}]
    adapters = {'approach_navigation': object()}
    assert validate_plan(params, stages, adapters) == ''
    assert validate_plan(params, stages, {}) == 'approach_controller_unavailable'
    assert validate_plan(params, [], adapters) == 'approach_unit_not_in_behavior_plan'
    assert validate_plan({**params, 'local_motion': {}}, stages, adapters) == 'approach_and_local_motion_conflict'
    params['approach']['mode'] = 'local_nav'
    assert validate_plan(params, stages, adapters) == 'approach_local_controller_unavailable'
    adapters['local_motion'] = SimpleNamespace(can_execute=lambda unit: unit == UNIT)
    assert validate_plan(params, stages, adapters) == ''
    adapters['approach_navigation'] = SimpleNamespace(recovery_required=True)
    assert validate_plan({}, stages, adapters) == 'approach_operator_recovery_required'


def test_original_header_and_roi_are_not_replaced_by_request_time():
    header, roi = geometry_request(PAYLOAD, TARGET_ID)
    assert header == {'sec': 123, 'nanosec': 250000000, 'frame_id': 'camera_optical'}
    assert roi == PAYLOAD['bbox']


@pytest.mark.parametrize('bad', [
    {'target_id': 'other'}, {'coordinate_space': 'normalized_bbox'},
    {'image_header': {'stamp': 0, 'frame_id': 'camera'}},
    {'image_header': {'stamp': float('nan'), 'frame_id': 'camera'}},
    {'bbox': {'x_offset': 600, 'y_offset': 0, 'width': 100, 'height': 10}},
    {'bbox': {'x_offset': 0, 'y_offset': 0, 'width': True, 'height': 10}},
])
def test_invalid_geometry_rejected(bad):
    with pytest.raises(ValueError):
        geometry_request({**PAYLOAD, **bad}, TARGET_ID)


def test_local_mode_converts_map_pose_without_mutating_request_and_propagates_cancel():
    calls = []
    def execute(unit, ctx, timeout, **kwargs):
        calls.append((copy.deepcopy(ctx.params), kwargs['cancel_check']()))
        ctx.metadata['local_motion'] = {'stop_confirmed': True}
        return SimpleNamespace(success=True, canceled=False, reason='arrived')
    transport = GeometryApproachTransport.__new__(GeometryApproachTransport)
    transport.local_adapter = SimpleNamespace(execute_task=execute)
    ctx = context()
    ctx.params['approach'] = {'mode': 'local_nav', 'unit_id': UNIT}
    before = copy.deepcopy(ctx.params)
    assert transport.navigate_approach(POSE, time.monotonic()+1, threading.Event(), ctx=ctx,
                                      unit_config={'unit_id': UNIT}) == (True, False, 'arrived')
    assert calls[0][0]['local_motion']['goal'] == {'frame_id': 'map', 'x': 1., 'y': 2., 'yaw': 0.}
    assert ctx.params == before and ctx.metadata['local_motion']['stop_confirmed']
    cancel = threading.Event(); cancel.set()
    assert not transport.navigate_approach(POSE, time.monotonic()+1, cancel, ctx=ctx,
                                          unit_config={'unit_id': UNIT})[0]
    assert len(calls) == 1


def test_local_mode_owns_chassis_once_and_keeps_voice_authorization():
    transport = Transport({'ok': True, 'target_id': TARGET_ID, 'status': 0,
        'navigation_required': True, 'person_point': PERSON_POINT, 'navigation_goal': POSE})
    calls = []
    transport.navigate_approach = lambda *args, **kw: calls.append(kw['ctx'].params['approach']['mode']) or (True, False, 'arrived')
    chassis = SimpleNamespace(prepare_navigation=lambda: pytest.fail('duplicate chassis preflight'),
                              finish_navigation=lambda: pytest.fail('duplicate chassis settlement'))
    adapter = PersonNavApproachAdapter(transport, lambda x: None, chassis_backend=chassis, allow_bound_target=True)
    ctx = context(); ctx.params['approach'] = {'mode': 'local_nav', 'unit_id': UNIT}
    assert adapter.execute_task({'unit_id': UNIT}, ctx, 1).success
    assert calls == ['local_nav']
    ctx.params['speaker_status'] = 'unknown'
    assert not adapter.execute_task({'unit_id': UNIT}, ctx, 1).success
    assert calls == ['local_nav']


def test_late_geometry_after_cancel_never_starts_navigation():
    class Late(Transport):
        def locate(self, target_id, distance, deadline, cancel):
            cancel.set()
            return self.result, 'ok'
    transport = Late({'ok': True, 'target_id': TARGET_ID, 'status': 0,
        'navigation_required': True, 'person_point': PERSON_POINT, 'navigation_goal': POSE})
    adapter = PersonNavApproachAdapter(transport, lambda x: None, allow_bound_target=True)
    result = adapter.execute_task({'unit_id': UNIT}, context(), 1)
    assert result.canceled and not result.success and transport.navigations == []
