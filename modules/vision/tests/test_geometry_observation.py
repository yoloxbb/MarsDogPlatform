from types import SimpleNamespace
import threading
import time
import numpy as np

from marsdog_vision_interaction.core.geometry_observation import frame_geometry
from marsdog_vision_interaction.core.visual_target_manager import VisualTargetManager
from marsdog_vision_interaction.core.task_router import run_task
from marsdog_vision_interaction.providers.vision_observation import VisionObservationProvider
from marsdog_vision_interaction.nodes.vision_interaction_node import VisionInteractionNode


HUMAN = {'x': .2, 'y': .1, 'w': .4, 'h': .8, 'confidence': .9}


def observation():
    mgr = VisualTargetManager(vision_epoch='geometry')
    mgr.update_vision([dict(HUMAN)], [])
    candidates = mgr.get_snapshot()['human_candidates']
    return mgr, candidates


def test_roi_uses_original_image_dimensions_and_exact_current_frame():
    _, candidates = observation()
    assert frame_geometry([HUMAN], candidates, 640, 480) == {
        candidates[0]['target_id']: {'x_offset': 128, 'y_offset': 48, 'width': 256, 'height': 384}}


def test_retained_ambiguous_and_stereo_boxes_cannot_be_localized():
    _, candidates = observation()
    assert frame_geometry([], candidates, 640, 480) == {}
    assert frame_geometry([HUMAN, HUMAN], candidates, 640, 480) == {}
    assert frame_geometry([HUMAN], candidates, 1280, 480, stereo_split=True) == {}
    assert frame_geometry([{**HUMAN, 'x': .21}], candidates, 640, 480) == {}


def test_provider_returns_original_header_and_rejects_stale_or_other_target():
    _, candidates = observation()
    target = candidates[0]['target_id']
    provider = VisionObservationProvider({})
    provider._cached_observation = {'_geometry_rois': frame_geometry([HUMAN], candidates, 640, 480),
        '_geometry_size': (640, 480), '_geometry_source': (123.25, 'rgb_optical', time.monotonic())}
    result = provider.get_geometry_observation(target, .35)
    assert result['ok'] and result['image_header'] == {'stamp': 123.25, 'frame_id': 'rgb_optical'}
    result['bbox']['width'] = 1
    assert provider.get_geometry_observation(target, .35)['bbox']['width'] != 1
    assert not provider.get_geometry_observation('new:human:1', .35)['ok']
    provider._cached_observation['_geometry_source'] = (123.25, 'rgb_optical', time.monotonic()-1)
    assert not provider.get_geometry_observation(target, .35)['ok']
    provider._cached_observation['_geometry_source'] = None
    assert not provider.get_geometry_observation(target, .35)['ok']


def test_task_dispatch_requires_current_target_and_geometry_provider():
    mgr, candidates = observation()
    target = candidates[0]['target_id']
    calls = []
    node = SimpleNamespace(_target_manager=mgr, _target_current_timeout_sec=.35,
        _providers={'vision': SimpleNamespace(get_geometry_observation=lambda *args: calls.append(args) or {'ok': True})})
    node._locate_person_once = lambda params: VisionInteractionNode._locate_person_once(node, params)
    node._locate_person_geometry = lambda params: VisionInteractionNode._locate_person_geometry(node, params)
    assert run_task(node, 'locate_person_geometry', {'target_id': target})['ok']
    assert calls == [(target, .35)]
    assert not run_task(node, 'locate_person_geometry', {'target_id': 'old:human:1'})['ok']
    assert len(calls) == 1
    node._providers = {}
    assert not run_task(node, 'locate_person_geometry', {'target_id': target})['ok']


def test_worker_keeps_provenance_with_the_inferred_frame(monkeypatch):
    provider = VisionObservationProvider({})
    provider.available = True
    provider._inference_frame_stride = 1
    inferred = threading.Event()
    def process(frame):
        inferred.set()
        return {'_geometry_rois': {'epoch:human:1': {'x_offset': 0, 'y_offset': 0, 'width': 2, 'height': 2}},
                '_geometry_size': (2, 2)}
    monkeypatch.setattr(provider, '_process_frame_impl', process)
    provider._start_inference_worker()
    try:
        provider.process_frame(np.zeros((2, 2, 3)), stamp=456.125, frame_id='camera_optical')
        assert inferred.wait(1)
        deadline = time.monotonic()+1
        while not provider.get_observation() and time.monotonic() < deadline:
            time.sleep(.001)
        result = provider.get_geometry_observation('epoch:human:1', .35)
        assert result['image_header'] == {'stamp': 456.125, 'frame_id': 'camera_optical'}
    finally:
        assert provider._stop_inference_worker()
