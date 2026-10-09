"""Expression contracts: synthetic data/fake RKNN only, no NPU or camera."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from marsdog_vision_interaction.api.face_api import FaceApiServer
from marsdog_vision_interaction.messages.facial_emotion import (
    EMOTIONS, expire_facial_emotions, normalize_facial_emotion,
)
from marsdog_vision_interaction.messages.visual_event import normalize_visual_event
from marsdog_vision_interaction.providers import emotion_backends as backend
from marsdog_vision_interaction.providers.gesture_pose_engine import FaceObservation
from marsdog_vision_interaction.providers import vision_observation as vision
from marsdog_vision_interaction.utils import visual_debug


@pytest.mark.parametrize("winner,label", enumerate(EMOTIONS))
def test_all_eight_winners_and_auxiliary_exclusion(winner, label):
    logits = np.full((1, 10), -1000.0, np.float32)
    logits[0, winner] = -995.0
    logits[0, 8:] = [1e30, -1e30]
    result = backend.decode_expression([logits])
    assert result == {"emotion": label, "intensity": pytest.approx(1 / (1 + 7 * np.exp(-5)))}
    assert backend.decode_expression([np.zeros((1, 10), np.float32)]) == {"emotion": "angry", "intensity": .125}


@pytest.mark.parametrize("outputs", [None, [], [np.zeros((10,), np.float32)],
    [np.zeros((1, 8), np.float32)], [np.zeros((1, 10), np.int32)],
    [np.full((1, 10), np.nan)], [np.full((1, 10), np.inf)],
    [np.zeros((1, 10)), np.zeros((1, 2))]])
def test_output_contract_rejects_bad_data(outputs):
    with pytest.raises(ValueError):
        backend.decode_expression(outputs)


def test_preprocess_is_exact_benchmark_parity():
    path = Path(__file__).parents[1] / "tools" / "benchmark_emotion_rknn.py"
    spec = importlib.util.spec_from_file_location("emotion_parity_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Non-square, noncontiguous input makes channel/order/resize differences visible.
    crop = np.random.default_rng(13).integers(0, 256, (47, 73, 3), dtype=np.uint8)[::2, ::2]
    tensor = backend.preprocess_face(crop)
    profile = module.MODEL_PROFILES["enet_b0_8_va_mtl_rk3588_fp.rknn"]
    expected = module._preprocess(crop, profile)
    np.testing.assert_array_equal(tensor, expected)
    legacy_profile = copy.deepcopy(profile)
    legacy_profile["input"]["layout"] = "nchw"
    previous_nchw = module._preprocess(crop, legacy_profile)
    np.testing.assert_array_equal(tensor.transpose(0, 3, 1, 2), previous_nchw)
    assert tensor.shape == (1, 224, 224, 3) and tensor.dtype == np.float32 and tensor.flags.c_contiguous
    outputs = [np.arange(10, dtype=np.float32).reshape(1, 10)]
    _, scores = module._normalize_outputs(outputs, module.MODEL_PROFILES["enet_b0_8_va_mtl_rk3588_fp.rknn"])
    assert backend.decode_expression(outputs)["intensity"] == float(scores.max())


@pytest.mark.parametrize("crop", [np.empty((0, 3, 3), np.uint8), np.zeros((3, 3), np.uint8), np.zeros((3, 3, 3), np.float32)])
def test_input_contract_rejects_bad_crops(crop):
    with pytest.raises(ValueError):
        backend.preprocess_face(crop)


class Runtime:
    NPU_CORE_AUTO = 0
    def __init__(self):
        self.released = 0
        self.calls = []
    def load_rknn(self, path):
        return 0
    def init_runtime(self, **kwargs):
        return 0
    def inference(self, **kwargs):
        self.calls.append(kwargs)
        return [np.zeros((1, 10), np.float32)]
    def release(self):
        self.released += 1


@pytest.fixture
def fake_runtime(monkeypatch, tmp_path):
    model = tmp_path / 'model.rknn'
    model.write_bytes(b'synthetic graph fixture')
    monkeypatch.setattr(backend, 'MODEL_SHA256', hashlib.sha256(model.read_bytes()).hexdigest())
    runtime = Runtime()
    factory = lambda: runtime
    factory.NPU_CORE_AUTO = 0
    monkeypatch.setitem(sys.modules, 'rknnlite.api', SimpleNamespace(RKNNLite=factory))
    monkeypatch.setattr(backend, 'configure_rknn_runtime', lambda *a: None)
    return model, runtime


def test_runtime_layout_and_idempotent_release(fake_runtime):
    model, runtime = fake_runtime
    adapter = backend.RknnEmotionBackend(str(model))
    assert adapter.infer(np.zeros((12, 8, 3), np.uint8))["intensity"] == .125
    assert runtime.calls[0]['data_format'] == ['nhwc']
    assert runtime.calls[0]['inputs'][0].shape == (1, 224, 224, 3)
    adapter.close()
    adapter.close()
    assert runtime.released == 1
    with pytest.raises(RuntimeError, match='closed'):
        adapter.infer(np.zeros((2, 2, 3), np.uint8))


def test_hash_guard_precedes_runtime_import(monkeypatch, tmp_path):
    path = tmp_path / 'unverified.rknn'
    path.write_bytes(b'wrong graph')
    calls = []
    monkeypatch.setattr(backend, 'configure_rknn_runtime', lambda *a: calls.append(a))
    with pytest.raises(ValueError, match='unverified'):
        backend.RknnEmotionBackend(str(path))
    assert calls == []
    with pytest.raises(FileNotFoundError):
        backend.RknnEmotionBackend(str(path.parent / 'missing.rknn'))


def test_init_failure_releases_runtime(fake_runtime):
    model, runtime = fake_runtime
    runtime.init_runtime = lambda **kw: -1
    with pytest.raises(RuntimeError, match='initialization'):
        backend.RknnEmotionBackend(str(model))
    assert runtime.released == 1


def provider():
    instance = vision.VisionObservationProvider({
        'face_emotion': {'enabled': True, 'min_face_size_px': 1}, 'stereo_enabled': False,
    })
    instance.available = True
    instance.emotion_model_status = {'enabled': True, 'ready': True}
    return instance


class Detector:
    def setInputSize(self, size):
        pass
    def detect(self, image):
        return 1, np.array([[-4, -3, 14, 13] + [2, 2] * 5 + [.99],
                            [12, 2, 8, 8] + [14, 4] * 5 + [.95]], np.float32)


class EmotionModel:
    def __init__(self):
        self.crops = []
        self.closed = 0
    def infer(self, crop):
        self.crops.append(crop.copy())
        return {'emotion': 'happy' if len(self.crops) == 1 else 'sad', 'intensity': .85}
    def close(self):
        self.closed += 1


def test_clipped_unknown_faces_keep_correct_expression_independent_of_identity():
    instance = provider()
    instance._face_detector = Detector()
    instance._emotion_backend = model = EmotionModel()
    image = np.arange(20 * 24 * 3, dtype=np.uint8).reshape(20, 24, 3)
    faces = instance._detect_faces(image, 24, 20)
    assert len(faces) == 2  # Also verifies the real timing trace call does not throw.
    assert faces[0]['facial_emotion'] == {'emotion': 'happy', 'intensity': .85}
    assert faces[1]['facial_emotion'] == {'emotion': 'sad', 'intensity': .85}
    assert all(face['recognized_user'] == '' and face['track_id'] == -1 for face in faces)
    np.testing.assert_array_equal(model.crops[0], image[:10, :10])
    np.testing.assert_array_equal(model.crops[1], image[2:10, 12:20])
    assert 'x1' not in faces[0]
    overlays = instance._debug_face_overlays(faces, SimpleNamespace(face_track_id=-1), False)
    assert [f['facial_emotion']['emotion'] for f in overlays] == ['happy', 'sad']


@pytest.mark.parametrize('min_face_size_px', [0, -1, True, False, 80.0, '80', None])
def test_invalid_emotion_min_face_size_is_rejected(min_face_size_px):
    with pytest.raises(ValueError, match='face_emotion.min_face_size_px must be a positive integer'):
        vision.VisionObservationProvider({'face_emotion': {'min_face_size_px': min_face_size_px}})


def test_missing_emotion_min_face_size_defaults_to_80_pixels():
    instance = vision.VisionObservationProvider({'face_emotion': {'enabled': True}})
    assert instance._emotion_min_face_size_px == 80


@pytest.mark.parametrize(('bbox', 'expected_crop_shape'), [
    ((0, 0, 79, 80), None),       # Width below the threshold.
    ((0, 0, 80, 79), None),       # Height below the threshold.
    ((0, 0, 80, 80), (80, 80)),   # Exactly at the threshold.
    ((0, 0, 81, 81), (81, 81)),   # Above the threshold in both dimensions.
    ((-1, 0, 79, 80), None),      # Clipping reduces width to 79 px.
    ((-1, 0, 80, 80), (80, 80)),  # Clipping leaves exactly 80 px.
    ((0, -1, 80, 79), None),      # Clipping reduces height to 79 px.
    ((0, -1, 80, 80), (80, 80)),  # Clipping leaves exactly 80 px.
])
def test_emotion_gate_uses_clipped_source_crop_dimensions(bbox, expected_crop_shape):
    instance = vision.VisionObservationProvider({
        'face_emotion': {'enabled': True, 'min_face_size_px': 80},
    })
    instance._emotion_backend = model = EmotionModel()
    x1, y1, x2, y2 = bbox
    face = {
        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
        'track_id': 7, 'recognized_user': 'known-person', 'identity_state': 'known',
    }

    instance._infer_face_emotions(np.zeros((100, 100, 3), dtype=np.uint8), [face], sequence=1)

    if expected_crop_shape is None:
        assert model.crops == []
        assert 'facial_emotion' not in face
    else:
        assert len(model.crops) == 1
        assert model.crops[0].shape[:2] == expected_crop_shape
        assert face['facial_emotion'] == {'emotion': 'happy', 'intensity': .85}
    assert face['track_id'] == 7
    assert face['recognized_user'] == 'known-person'
    assert face['identity_state'] == 'known'


def test_failure_on_second_face_clears_first_and_isolates_capability():
    instance = provider()
    instance._face_detector = Detector()
    instance._emotion_backend = model = EmotionModel()
    def failing(crop):
        model.crops.append(crop.copy())
        if len(model.crops) == 2:
            raise RuntimeError('runtime failed')
        return {'emotion': 'happy', 'intensity': .9}
    model.infer = failing
    faces = instance._detect_faces(np.zeros((20, 24, 3), np.uint8), 24, 20)
    assert len(faces) == 2 and all('facial_emotion' not in face for face in faces)
    assert instance.available and instance._face_detector is not None
    assert instance.get_facial_emotion()['status'] == 503
    assert model.closed == 1
    instance._detect_faces(np.zeros((20, 24, 3), np.uint8), 24, 20)
    assert len(model.crops) == 2


def test_disabled_default_does_not_construct_backend(monkeypatch):
    instance = vision.VisionObservationProvider({})
    monkeypatch.setattr(backend, 'RknnEmotionBackend', lambda *a, **kw: pytest.fail('must not load RKNN'))
    instance._start_emotion_backend()
    assert instance.get_facial_emotion()['status'] == 503


def test_init_failure_is_reported_without_disabling_provider(monkeypatch):
    instance = provider()
    def fail(*a, **kw):
        raise RuntimeError('not installed')
    monkeypatch.setattr(backend, 'RknnEmotionBackend', fail)
    instance._start_emotion_backend()
    assert instance.available and not instance.emotion_model_status['ready']
    assert instance.get_facial_emotion()['status'] == 503


def test_unavailable_provider_restart_releases_previous_emotion_backend(monkeypatch):
    instance = vision.VisionObservationProvider({
        'face_emotion': {'enabled': True}, 'face_tracking': {'use_bytetrack': False},
        'hand_landmark_model': '',
    })
    models = []
    def create(*a, **kw):
        model = EmotionModel()
        models.append(model)
        return model
    monkeypatch.setattr(backend, 'RknnEmotionBackend', create)
    instance.start()
    assert not instance.available and models[0].closed == 0
    instance.start()
    assert not instance.available and models[0].closed == 1
    assert instance._emotion_backend is models[1]
    instance.stop()
    instance.stop()
    assert [model.closed for model in models] == [1, 1]


def current_face(track, emotion='happy', bbox=(.1, .1, .2, .2)):
    return {'track_id': track, 'x': bbox[0], 'y': bbox[1], 'w': bbox[2], 'h': bbox[3],
            'facial_emotion': {'emotion': emotion, 'intensity': .85},
            '_behavior_face_observation': FaceObservation(bbox=bbox, confidence=.9, track_id=track)}


def test_retained_active_face_cannot_receive_other_track_or_bbox_result():
    active = SimpleNamespace(face_track_id=3, face_bbox=(.1, .1, .2, .2), bbox=(0, 0, .5, 1))
    matching, other = current_face(3), current_face(4, 'sad')
    assert vision.VisionObservationProvider._current_emotion_face(active, [other, matching]) is matching
    assert vision.VisionObservationProvider._current_emotion_face(active, [other]) is None
    assert vision.VisionObservationProvider._current_emotion_face(active, [current_face(3, bbox=(.8, .8, .1, .1))]) is None
    active.face_track_id = -1
    assert vision.VisionObservationProvider._current_emotion_face(active, [matching]) is matching


def cache(instance, now=10.0, faces=None, active=None):
    faces = faces if faces is not None else [current_face(1)]
    instance._emotion_faces = faces
    instance._emotion_active_index = active
    instance._emotion_source_monotonic = now
    instance._cached_observation = {'faces': copy.deepcopy(faces), 'debug_faces': copy.deepcopy(faces)}


def test_api_selection_and_source_expiry_are_shared_with_debug(monkeypatch):
    instance = provider()
    now = [10.1]
    monkeypatch.setattr(vision.time, 'monotonic', lambda: now[0])
    cache(instance, faces=[current_face(1), current_face(2, 'sad')])
    assert instance.get_facial_emotion()['status'] == 409
    assert instance.get_facial_emotion(2) == {'ok': True, 'emotion': 'sad', 'intensity': .85}
    assert instance.get_facial_emotion(3)['status'] == 404
    instance._emotion_active_index = 0
    assert instance.get_facial_emotion()['emotion'] == 'happy'
    assert instance.get_observation()['facial_emotion_valid_for_sec'] == pytest.approx(.4)
    now[0] = 10.51
    # Unrelated fresh camera/pending frame does not refresh the inferred source.
    instance._pending_frame_monotonic = now[0]
    for _ in range(3):
        assert instance.get_facial_emotion()['status'] == 404
        observation = instance.get_observation()
        assert all('facial_emotion' not in face for key in ('faces', 'debug_faces') for face in observation[key])
    cache(instance, now=now[0], faces=[])
    assert instance.get_facial_emotion()['status'] == 404
    cache(instance, now=now[0], faces=[current_face(9, 'fear')])
    assert instance.get_facial_emotion(1)['status'] == 404
    assert instance.get_facial_emotion()['emotion'] == 'fear'
    instance.task_face_enabled = False
    assert instance.get_facial_emotion()['status'] == 404


def test_worker_ages_from_frame_receipt_and_invalidates_failed_frames(monkeypatch):
    instance = provider()
    entered, finish, completed = threading.Event(), threading.Event(), threading.Event()
    def process(frame):
        if frame[0, 0, 0] == 1:
            raise RuntimeError('frame failed')
        entered.set()
        assert finish.wait(2)
        completed.set()
        return {'faces': [current_face(1)], '_facial_emotion_faces': [current_face(1)], '_facial_emotion_active_index': 0}
    monkeypatch.setattr(instance, '_process_frame_impl', process)
    instance._start_inference_worker()
    try:
        instance.process_frame(np.zeros((2, 2, 3), np.uint8))
        assert entered.wait(2)
        receipt = instance._pending_frame_monotonic
        instance._pending_frame_monotonic = receipt + 100  # newer activity must not age this frame
        finish.set()
        assert completed.wait(2)
        deadline = time.monotonic() + 2
        while instance._inferred_frame_count < 1 and time.monotonic() < deadline:
            time.sleep(.005)
        assert instance._emotion_source_monotonic == receipt
        assert instance.get_facial_emotion()['emotion'] == 'happy'
        instance.process_frame(np.ones((2, 2, 3), np.uint8))
        deadline = time.monotonic() + 2
        while instance._emotion_source_monotonic != 0 and time.monotonic() < deadline:
            time.sleep(.005)
        assert instance.get_facial_emotion()['status'] == 404
        assert 'facial_emotion' not in instance.get_observation()['faces'][0]
    finally:
        finish.set()
        instance.stop()


def test_stop_preserves_live_worker_then_releases_emotion_once(monkeypatch):
    instance = provider()
    instance._emotion_backend = model = EmotionModel()
    monkeypatch.setattr(instance, '_stop_inference_worker', lambda: False)
    instance.stop()
    assert model.closed == 0 and instance._emotion_backend is model
    assert instance.get_facial_emotion()['status'] == 503
    monkeypatch.setattr(instance, '_stop_inference_worker', lambda: True)
    instance.stop()
    instance.stop()
    assert model.closed == 1


@pytest.mark.parametrize('value', [{'emotion': 'anger', 'intensity': .5},
    {'emotion': 'happy', 'intensity': True}, {'emotion': 'happy', 'intensity': float('nan')},
    {'emotion': 'happy', 'intensity': 1.1}, {'emotion': 'happy', 'intensity': '0.8'}])
def test_bad_optional_results_omitted_from_public_contract(value):
    assert normalize_facial_emotion(value) is None
    event = normalize_visual_event({'faces': [{'facial_emotion': value}], 'debug_faces': [{'facial_emotion': value}]})
    assert 'facial_emotion' not in event['faces'][0] and 'facial_emotion' not in event['debug_faces'][0]


def test_normalization_and_debug_expiry_preserve_original_probability():
    value = {'emotion': 'happy', 'intensity': .85123456789, 'other': 7}
    event = normalize_visual_event({'faces': [{'facial_emotion': value}],
                                    'debug_faces': [{'facial_emotion': value}], 'facial_emotion_valid_for_sec': .2})
    assert event['faces'][0]['facial_emotion'] == {'emotion': 'happy', 'intensity': .85123456789}
    expire_facial_emotions(event, .1)
    assert 'facial_emotion' in event['debug_faces'][0]
    expire_facial_emotions(event, .11)
    assert all('facial_emotion' not in face for key in ('faces', 'debug_faces') for face in event[key])


def test_osd_labels_show_associated_category_probability(monkeypatch):
    labels = []
    monkeypatch.setattr(visual_debug, '_text', lambda image, text, *a, **kw: labels.append(text))
    visual_debug.draw_visual_debug(np.zeros((120, 180, 3), np.uint8),
        {'faces': [current_face(1, 'happy'), current_face(2, 'sad')]})
    assert any('face id=1' in text and 'happy 0.85' in text for text in labels)
    assert any('face id=2' in text and 'sad 0.85' in text for text in labels)


def request(server, path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.create_app()), base_url='http://test') as client:
            return await client.get(path)
    return asyncio.run(run())


def server(handler=None):
    return FaceApiServer({}, *([lambda *a: {'ok': True}] * 6), emotion_handler=handler)


def test_http_openapi_documents_exact_expression_schema():
    operation = server().create_app().openapi()['paths']['/api/v1/faces/emotion']['get']
    schema = operation['responses']['200']['content']['application/json']['schema']
    assert set(schema['required']) == {'emotion', 'intensity'}
    assert schema['additionalProperties'] is False
    assert schema['properties']['emotion']['enum'] == list(EMOTIONS)
    assert schema['properties']['intensity'] == {'type': 'number', 'minimum': 0, 'maximum': 1}
    assert set(operation['responses']) == {'200', '404', '409', '422', '503'}


def test_exact_http_success_and_error_matrix(monkeypatch):
    instance = provider()
    monkeypatch.setattr(vision.time, 'monotonic', lambda: 10.1)
    cache(instance)
    api = server(instance.get_facial_emotion)
    result = request(api, '/api/v1/faces/emotion')
    assert result.status_code == 200 and result.json() == {'emotion': 'happy', 'intensity': .85}
    assert request(api, '/api/v1/faces/emotion?track_id=123').status_code == 404
    assert request(api, '/api/v1/faces/emotion?track_id=nope').status_code == 422
    assert request(api, '/api/v1/faces/emotion?track_id=-1').status_code == 422
    cache(instance, faces=[current_face(1), current_face(2, 'sad')])
    assert request(api, '/api/v1/faces/emotion').status_code == 409
    assert request(api, '/api/v1/faces/emotion?track_id=2').json() == {'emotion': 'sad', 'intensity': .85}
    instance.emotion_model_status['ready'] = False
    result = request(api, '/api/v1/faces/emotion')
    assert result.status_code == 503 and set(result.json()) == {'detail', 'request_id'}
    assert request(server(), '/api/v1/faces/emotion').status_code == 503


def test_processed_active_fallback_and_all_detections_keep_same_frame_results(monkeypatch):
    from marsdog_vision_interaction.core.visual_target_manager import ActiveVisualTarget
    from marsdog_vision_interaction.fusion import stereo_fusion

    instance = provider()
    instance._show_all_detections = True
    active = ActiveVisualTarget(track_id=1, face_track_id=3, bbox=(0, 0, .5, 1),
        face_bbox=(.1, .1, .2, .2), face_confidence=.9, confidence=.9, last_seen_at=time.time(), last_seen_monotonic=time.monotonic())
    snapshot = {'active_target': active, 'human_candidates': [], 'vision_epoch': 'test'}
    manager = SimpleNamespace(update_vision=lambda **kw: None, get_snapshot=lambda: snapshot)
    monkeypatch.setattr(stereo_fusion, 'get_target_manager', lambda: manager)
    faces = [current_face(4, 'sad', (.7, .1, .2, .2)), current_face(3, 'happy')]
    monkeypatch.setattr(instance, '_run_inference', lambda *a, **kw: {'faces': faces, 'humans': [], 'hands': []})
    image = np.zeros((32, 32, 3), np.uint8)
    result = instance._process_frame_impl(image)
    assert result['faces'][0]['track_id'] == 3
    assert result['faces'][0]['facial_emotion']['emotion'] == 'happy'
    assert [face['facial_emotion']['emotion'] for face in result['debug_faces']] == ['sad', 'happy']
    assert result['_facial_emotion_active_index'] == 1
    # A retained active target's face ID cannot acquire current unrelated evidence.
    faces[:] = [current_face(4, 'sad', (.7, .1, .2, .2))]
    result = instance._process_frame_impl(image)
    assert 'facial_emotion' not in result['faces'][0]
    assert result['_facial_emotion_active_index'] is None
    active.face_confidence = 0
    result = instance._process_frame_impl(image)
    assert result['faces'][0]['track_id'] == 4 and result['faces'][0]['facial_emotion']['emotion'] == 'sad'


def test_repeated_publications_cannot_extend_same_source_viewer_deadline():
    from marsdog_vision_interaction.messages.facial_emotion import FacialEmotionExpiry
    expiry = FacialEmotionExpiry()
    def packet(stamp, sequence):
        return {'vision_epoch': 'epoch', 'header': {'stamp': stamp, 'frame_id': 'camera'},
                'sequence': sequence, 'faces': [current_face(1)], 'facial_emotion_valid_for_sec': .4}
    first = packet(123, 1)
    expiry.apply(first, 10)
    repeated = packet(123, 2)
    expiry.apply(repeated, 10.3)
    assert repeated['facial_emotion_valid_for_sec'] == pytest.approx(.1)
    expired = packet(123, 3)
    expiry.apply(expired, 10.41)
    assert 'facial_emotion' not in expired['faces'][0]
    assert 'facial_emotion_valid_for_sec' not in expired
    new_source = packet(124, 4)
    expiry.apply(new_source, 10.5)
    assert new_source['facial_emotion_valid_for_sec'] == pytest.approx(.4)
