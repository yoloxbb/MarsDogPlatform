"""Provider integration contracts for the format-selected face adapters."""

from __future__ import annotations

import threading
import time

import numpy as np
from marsdog_vision_interaction.providers import face_recognition, vision_observation
from marsdog_vision_interaction.providers.face_backends import FaceBackendError


class FaceModel:
    def __init__(self):
        self.closed = 0
        self.images = []

    def close(self):
        self.closed += 1

    def feature(self, image):
        self.images.append(image.copy())
        return np.ones((1, 128), np.float32)


class FatalDetector(FaceModel):
    fatal_error = "YuNet inference failed: runtime context was released"

    def setInputSize(self, input_size):
        pass

    def detect(self, frame):
        raise FaceBackendError(self.fatal_error)


class FatalRecognizer(FaceModel):
    fatal_error = "SFace inference failed: runtime context was released"

    def feature(self, image):
        raise FaceBackendError(self.fatal_error)


def vision_config():
    return {
        'face_detect_model': 'detector.rknn',
        'face_recogn_model': 'recognizer.rknn',
        'face_detect_rknn': {'profile': 'yunet_2023mar_fp16'},
        'face_recogn_rknn': {'profile': 'sface_2021dec_fp16'},
        'hand_landmark_model': '',
        'mediapipe_model': '',
        'face_tracking': {'use_bytetrack': False},
    }


def test_observation_factories_receive_profiles_and_release_once(monkeypatch):
    detector, recognizer = FaceModel(), FaceModel()
    calls = []
    monkeypatch.setattr(vision_observation, 'create_face_detector',
                        lambda path, **kwargs: (calls.append((path, kwargs)), detector)[1])
    monkeypatch.setattr(vision_observation, 'create_face_recognizer',
                        lambda path, **kwargs: (calls.append((path, kwargs)), recognizer)[1])
    provider = vision_observation.VisionObservationProvider(vision_config())
    try:
        provider.start()
        provider.start()
        assert provider.available
        assert len(calls) == 2
        assert calls[0][0] == 'detector.rknn'
        assert calls[0][1]['rknn_config']['profile'] == 'yunet_2023mar_fp16'
        assert calls[1][1]['rknn_config']['profile'] == 'sface_2021dec_fp16'
        assert provider.face_model_status == {'yunet': {'ready': True}, 'sface': {'ready': True}}
    finally:
        provider.stop()
        provider.stop()
    assert detector.closed == recognizer.closed == 1


def test_observation_failed_recognition_setup_releases_loaded_model(monkeypatch):
    detector, recognizer = FaceModel(), FaceModel()
    monkeypatch.setattr(vision_observation, 'create_face_detector', lambda *a, **k: detector)
    monkeypatch.setattr(vision_observation, 'create_face_recognizer', lambda *a, **k: recognizer)
    config = vision_config()
    config['face_recognition_throttle'] = {'min_face_score': 'invalid'}
    provider = vision_observation.VisionObservationProvider(config)
    try:
        provider.start()
        assert provider.available  # Detector still works; SFace failure is explicit.
        assert not provider.face_model_status['sface']['ready']
        assert provider._face_rec_model is None
        assert recognizer.closed == 1
    finally:
        provider.stop()
    assert recognizer.closed == 1


def test_standalone_uses_same_feature_contract_without_normalizing_twice(monkeypatch):
    model = FaceModel()
    calls = []
    monkeypatch.setattr(face_recognition, 'create_face_recognizer',
                        lambda path, **kwargs: (calls.append((path, kwargs)), model)[1])
    config = {'face_recogn_model': 'model.rknn',
              'face_recogn_rknn': {'profile': 'sface_2021dec_fp16'}}
    provider = face_recognition.FaceRecognitionProvider(config)
    image = np.full((37, 49, 3), 127, dtype=np.uint8)
    try:
        assert provider.enroll(image, 'owner')['success']
        assert provider.recognize(image)['matched']
        assert len(calls) == 1
        np.testing.assert_array_equal(model.images[0], image)
        assert provider._enrolled['owner'][0].shape == (128,)
    finally:
        provider.stop()
    assert model.closed == 1
    assert provider.enrolled_count == 0
    assert provider._extract_embedding(image) is None
    assert len(calls) == 1


def test_standalone_load_failure_is_visible_without_fallback(monkeypatch):
    calls = []

    def fail(path, **kwargs):
        calls.append(path)
        raise ValueError('Unverified RKNN artifact')

    monkeypatch.setattr(face_recognition, 'create_face_recognizer', fail)
    provider = face_recognition.FaceRecognitionProvider({'face_recogn_model': 'bad.rknn'})
    provider.start()
    image = np.zeros((112, 112, 3), np.uint8)
    assert not provider.enroll(image, 'owner')['success']
    assert not provider.available
    assert provider.model_error == 'Unverified RKNN artifact'
    assert not provider.enroll(image, 'owner')['success']
    assert calls == ['bad.rknn']
    provider.stop()


def test_standalone_stop_waits_for_inference_and_clears_templates(monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    model = FaceModel()

    def feature(image):
        entered.set()
        assert finish.wait(3)
        assert model.closed == 0
        return np.ones((1, 128), np.float32)

    model.feature = feature
    monkeypatch.setattr(face_recognition, 'create_face_recognizer', lambda *a, **k: model)
    provider = face_recognition.FaceRecognitionProvider({'face_recogn_model': 'model.rknn'})
    failures = []

    def enroll():
        try:
            provider.enroll(np.zeros((112, 112, 3), np.uint8), 'owner')
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=enroll)
    stopper = threading.Thread(target=provider.stop)
    worker.start()
    try:
        assert entered.wait(3)
        stopper.start()
        assert model.closed == 0
    finally:
        finish.set()
        worker.join(3)
        if stopper.ident is not None:
            stopper.join(3)
    assert not failures
    assert not worker.is_alive() and not stopper.is_alive()
    assert model.closed == 1
    assert provider.enrolled_count == 0


def test_observation_does_not_release_or_replace_live_worker_models(monkeypatch):
    detector = FaceModel()
    provider = vision_observation.VisionObservationProvider(vision_config())
    provider._face_detector = detector
    provider._worker = type('LiveWorker', (), {'is_alive': lambda self: True})()
    monkeypatch.setattr(provider, '_stop_inference_worker', lambda: False)
    calls = []
    monkeypatch.setattr(vision_observation, 'create_face_detector', lambda *a, **k: calls.append(a))
    provider.stop()
    provider.start()
    assert detector.closed == 0
    assert provider._face_detector is detector
    assert calls == []
    assert not provider.available


def test_observation_disables_fatal_yunet_once_and_marks_status():
    provider = vision_observation.VisionObservationProvider(vision_config())
    detector = FatalDetector()
    provider._face_detector = detector
    provider.face_model_status["yunet"] = {"ready": True}
    frame = np.zeros((32, 32, 3), np.uint8)

    assert provider._detect_faces(frame, 32, 32) == []
    assert detector.closed == 1
    assert provider._face_detector is None
    assert provider.face_model_status["yunet"] == {
        "ready": False,
        "fatal": True,
        "error": detector.fatal_error,
    }
    # The dead adapter is removed, so subsequent frames do not retry or close
    # it again while missing-track synchronization still runs.
    assert provider._detect_faces(frame, 32, 32) == []
    assert detector.closed == 1


def test_independent_recognizer_exposes_fatal_runtime_failure(monkeypatch):
    model = FatalRecognizer()
    calls = []
    monkeypatch.setattr(
        face_recognition,
        "create_face_recognizer",
        lambda path, **kwargs: (calls.append(path), model)[1],
    )
    provider = face_recognition.FaceRecognitionProvider(
        {"face_recogn_model": "broken.rknn"}
    )
    provider.start()
    image = np.zeros((112, 112, 3), np.uint8)
    assert provider.enroll(image, "owner")["success"] is False
    assert provider.available is False
    assert provider._recognizer is None
    assert provider.model_error == model.fatal_error
    assert provider.enroll(image, "owner")["success"] is False
    assert calls == ["broken.rknn"]
    provider.stop()


def test_observation_disables_fatal_sface_once():
    provider = vision_observation.VisionObservationProvider(vision_config())
    recognizer = FatalRecognizer()

    class Throttle:
        enrolled_count = 1
        _enrolled_embeddings = {}
        _cosine_threshold = .36

    provider._face_rec_model = recognizer
    provider._face_rec_throttle = Throttle()
    provider.face_model_status["sface"] = {"ready": True}
    face = {
        "x1": 0,
        "y1": 0,
        "x2": 32,
        "y2": 32,
        "track_id": 1,
        "_yunet_detection": np.array([0, 0, 32, 32] + [8, 8] * 5 + [.9], np.float32),
    }
    result = provider._run_sface(np.zeros((32, 32, 3), np.uint8), face)
    assert result == ("unknown", 0.0)
    assert recognizer.closed == 1
    assert provider._face_rec_model is None
    assert provider.face_model_status["sface"]["ready"] is False
    assert provider.face_model_status["sface"]["fatal"] is True


def test_fatal_sface_clears_all_visible_track_identities():
    from marsdog_vision_interaction.providers.face_tracker import FaceRecognitionThrottle

    provider = vision_observation.VisionObservationProvider(vision_config())

    class Detector:
        def setInputSize(self, size):
            pass

        def detect(self, frame):
            rows = np.array(
                [
                    [0, 0, 48, 48] + [8, 8] * 5 + [.9],
                    [80, 0, 48, 48] + [88, 8] * 5 + [.9],
                ],
                dtype=np.float32,
            )
            return 1, rows

    class Tracker:
        def update(self, xyxy, scores):
            return [1, 2]

    class FailsOnSecondRecognizer(FaceModel):
        fatal_error = None

        def __init__(self):
            super().__init__()
            self.calls = 0

        def feature(self, image):
            self.calls += 1
            if self.calls == 2:
                self.fatal_error = "SFace inference failed on second track"
                raise FaceBackendError(self.fatal_error)
            return np.ones((1, 128), np.float32)

    recognizer = FailsOnSecondRecognizer()
    throttle = FaceRecognitionThrottle(
        recognizer,
        min_face_score=.1,
        min_face_size_px=1,
        confirm_known_count=1,
    )
    throttle.set_enrolled_embeddings({"owner": [np.ones(128, np.float32)]})
    for track_id, name in ((1, "owner"), (2, "family")):
        state = throttle._get_or_create(track_id, time.time())
        state.identity = name
        state.identity_state = "confirmed_known"
        state.identity_confidence = .99
        state.recognition_attempts = 1
        state.last_recognition_ts = 0.0

    provider._face_detector = Detector()
    provider._face_tracker = Tracker()
    provider._face_rec_model = recognizer
    provider._face_rec_throttle = throttle
    provider.face_model_status["sface"] = {"ready": True}
    frame = np.zeros((64, 160, 3), np.uint8)
    faces = provider._detect_faces(frame, 160, 64)
    assert len(faces) == 2
    assert all(face["recognized_user"] == "" for face in faces)
    assert all(face["identity_state"] == "unverified" for face in faces)
    assert all(
        throttle.get_track_state(track_id).identity == "unknown"
        for track_id in (1, 2)
    )
    assert recognizer.calls == 2
    assert provider.face_model_status["sface"]["fatal"] is True

    # The next frame skips the dead recognizer and still cannot publish the
    # identities that were visible before the fatal transition.
    faces = provider._detect_faces(frame, 160, 64)
    assert all(face["recognized_user"] == "" for face in faces)
    assert recognizer.closed == 1
