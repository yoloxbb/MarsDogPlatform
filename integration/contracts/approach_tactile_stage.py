"""Independent module workers for additive geometry and tactile contracts."""
from pathlib import Path
import threading
import time
from worker_support import serve


def vision(request):
    from marsdog_vision_interaction.core import geometry_observation as module
    from marsdog_vision_interaction.providers.vision_observation import VisionObservationProvider
    human = {'x': .2, 'y': .1, 'w': .4, 'h': .8}
    expected = request
    target = expected['target_id']
    candidates = [{'target_id': target, 'tracking_state': 'tracking', 'bbox': [.2, .1, .4, .8]}]
    provider = VisionObservationProvider({})
    provider._cached_observation = {
        '_geometry_rois': module.frame_geometry([human], candidates, 640, 480),
        '_geometry_size': (640, 480), '_geometry_source': (123.25, 'camera_optical', time.monotonic())}
    produced = provider.get_geometry_observation(target, .35)
    assert produced == expected
    return produced, module.__file__


def action(request):
    from marsdog_action_executor.adapters import geometry_approach_transport as module
    header, roi = module.geometry_request(request, request['target_id'])
    assert header == {'sec': 123, 'nanosec': 250000000, 'frame_id': 'camera_optical'}
    assert roi == request['bbox']
    return {'header': header, 'roi': roi}, module.__file__


def behavior(cases):
    from marsdog_behavior import tactile_events as module
    observed = {}
    for case in cases:
        candidates = []
        consumer = module.TactileEventConsumer.from_file(Path('config/tactile_events.yaml'), candidates.append,
            wall_time=lambda: 100., monotonic=lambda: 1.)
        event = {'schema_version': '1.0', 'event_type': case['event'], 'source': 'contract-sensor',
                 'sensorType': 'TOUCH', 'touchState': 'STARTED', 'timestamp': 100.}
        consumer.consume(event)
        value = candidates[0].behavior_name if candidates else None
        assert value == case['behavior']
        if candidates:
            assert candidates[0].source == 'touch_direct'
        observed[case['event']] = value
    return observed, module.__file__


def emotion(cases):
    from marsdog_ros2 import perception_adapter as module
    from marsdog_core import MarsdogEmotionSystem
    observed = {}
    for case in cases:
        system = MarsdogEmotionSystem()
        before = dict(system.state.emotions)
        module.ApplyTactileEventMessage(system, {'schema_version': '1.0', 'event_type': case['event'],
            'source': 'contract-sensor', 'sensorType': 'TOUCH', 'touchState': 'STARTED', 'timestamp': 100.})
        deltas = {k: v-before[k] for k, v in system.state.emotions.items() if v != before[k]}
        assert deltas == case['deltas'], (case['event'], deltas)
        observed[case['event']] = deltas
    return observed, module.__file__


if __name__ == '__main__':
    serve({'vision': vision, 'action': action, 'behavior': behavior, 'emotion': emotion})
