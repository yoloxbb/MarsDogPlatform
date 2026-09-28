"""Shared upload/continuous enrollment quality and configuration contracts."""
import cv2
import numpy as np
import pytest

import marsdog_vision_interaction.core.face_enrollment_manager as storage
from marsdog_vision_interaction.core.face_enrollment_manager import FaceEnrollmentManager


class Detector:
    def __init__(self, confidence=.8, count=1, valid_landmarks=True):
        self.confidence = confidence
        self.count = count
        self.valid_landmarks = valid_landmarks

    def setInputSize(self, size):
        pass

    def detect(self, frame):
        row = [0, 0, 120, 120, 35, 35, 85, 35, 60, 60, 40, 85, 80, 85, self.confidence]
        if not self.valid_landmarks:
            row[4:14] = [0] * 10
        return None, np.asarray([row] * self.count, dtype=float).reshape((-1, 15))


@pytest.fixture
def frame():
    gray = np.indices((120, 120)).sum(axis=0) % 2 * 80 + 80
    return np.repeat(gray.astype(np.uint8)[..., None], 3, axis=2)


@pytest.fixture(autouse=True)
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, '_STORAGE_ROOT', tmp_path)
    monkeypatch.setattr(storage, '_FACES_DIR', tmp_path / 'faces')
    monkeypatch.setattr(storage, '_REGISTRY_PATH', tmp_path / 'face_registry.json')


def image_bytes(frame):
    return cv2.imencode('.png', frame)[1].tobytes()


@pytest.mark.parametrize('threshold,passed', [(.85, False), (.8, True), (.7, True)])
def test_shared_confidence_boundary_and_diagnostics(frame, threshold, passed):
    manager = FaceEnrollmentManager({'quality': {'min_detection_confidence': threshold}})
    manager.set_face_detector(Detector())
    upload = manager._prepare_uploaded_face(image_bytes(frame))
    manager.start_face('owner')
    continuous = manager.process_face_frame(frame)
    assert upload['quality'] == continuous['quality']
    assert upload['quality']['passed'] is passed
    assert upload['ok'] is passed
    assert upload['quality']['metrics']['detection_confidence'] == .8
    assert upload['quality']['metrics']['brightness'] == 120
    assert upload['quality']['metrics']['blur_score'] > 35
    assert upload['quality']['thresholds']['min_detection_confidence'] == threshold
    assert upload['quality']['reason'] == (None if passed else 'low_detection_confidence')


@pytest.mark.parametrize('quality,reason', [
    ({'min_face_size_px': 121}, 'face_too_small'),
    ({'min_brightness': 121}, 'too_dark'),
    ({'max_brightness': 119}, 'overexposed'),
    ({'min_blur_score': 1e9}, 'blurry'),
])
def test_configured_quality_gates(frame, quality, reason):
    manager = FaceEnrollmentManager({'quality': quality})
    manager.set_face_detector(Detector(.99))
    assert manager._prepare_uploaded_face(image_bytes(frame))['quality']['reason'] == reason


@pytest.mark.parametrize('config', [
    [], {'quality': None}, {'continuous': []}, {'quality': {'typo': 1}},
    {'quality': {'min_detection_confidence': float('nan')}},
    {'quality': {'min_blur_score': float('inf')}},
    {'quality': {'min_detection_confidence': 1.1}},
    {'quality': {'min_detection_confidence': -.1}},
    {'quality': {'min_detection_confidence': '0.7'}},
    {'quality': {'require_single_face': 'false'}},
    {'quality': {'min_face_size_px': True}},
    {'quality': {'min_face_size_px': 80.5}},
    {'quality': {'min_brightness': 230}},
    {'quality': {'max_brightness': 256}},
    {'continuous': {'stable_frames': 0}},
    {'continuous': {'stable_frames': 1.2}},
    {'continuous': {'required_shots': 6}},
])
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        FaceEnrollmentManager(config)


@pytest.mark.parametrize('count,required,reason', [(0, True, 'no_face'), (2, True, 'multiple_faces'), (2, False, None)])
def test_face_count_policy_shared(frame, count, required, reason):
    manager = FaceEnrollmentManager({'quality': {'require_single_face': required}})
    manager.set_face_detector(Detector(.99, count=count))
    upload = manager._prepare_uploaded_face(image_bytes(frame))
    manager.start_face('owner')
    continuous = manager.process_face_frame(frame)
    assert upload['quality'] == continuous['quality']
    assert upload['quality']['reason'] == reason


def test_invalid_production_landmarks_rejected(frame):
    manager = FaceEnrollmentManager()
    manager.set_face_detector(Detector(.99, valid_landmarks=False))
    assert manager._prepare_uploaded_face(image_bytes(frame))['quality']['reason'] == 'invalid_landmarks'


def test_defaults_capacity_and_configured_stability(frame, tmp_path):
    manager = FaceEnrollmentManager({'continuous': {'stable_frames': 2, 'required_shots': 4}})
    manager.set_face_detector(Detector(.99))
    directory = tmp_path / 'faces' / 'owner'
    directory.mkdir()
    for sample in (1, 2, 3, 4):
        (directory / f'{sample:03d}.jpg').write_bytes(b'existing')
    assert manager.start_face('owner', 2)['status'] == 409
    assert manager.start_face('owner')['total_steps'] == 1
    assert manager.process_face_frame(frame)['status'] == 'tracking'
    manager._face_detector.confidence = .5
    assert manager.process_face_frame(frame)['status'] == 'searching'
    manager._face_detector.confidence = .99
    assert manager.process_face_frame(frame)['status'] == 'tracking'
    assert manager.process_face_frame(frame)['status'] == 'done'
    assert manager.start_face('owner')['status'] == 409


def test_continuous_enrollment_rejects_duplicate_without_advancing(frame):
    manager = FaceEnrollmentManager({
        'quality': {'min_brightness': 0.0, 'min_blur_score': 0.0},
        'continuous': {'stable_frames': 1, 'required_shots': 2},
    })
    manager.set_face_detector(Detector(.99))
    assert manager.start_face('owner')['ok'] is True

    first = manager.process_face_frame(frame)
    duplicate = manager.process_face_frame(frame)

    assert first['status'] == 'captured'
    assert duplicate['status'] == 'duplicate'
    assert duplicate['code'] == 'face_sample_duplicate'
    assert duplicate['duplicate_sample_id'] == 1
    assert duplicate['shots'] == 1
    assert manager.face_session is not None
    assert manager.face_session.shots_collected == 1
    assert manager.face_session.current_step == 2


def test_successful_upload_returns_diagnostics(frame):
    manager = FaceEnrollmentManager()
    manager.set_face_detector(Detector(.99))
    result = manager.enroll_face_from_image('owner', image_bytes(frame))
    assert result['quality']['passed']
    replacement = manager.replace_face_sample('owner', 1, image_bytes(frame))
    assert replacement['quality'] == result['quality']


def test_default_threshold_and_largest_face_policy(frame):
    manager = FaceEnrollmentManager({'quality': {'require_single_face': False}})
    manager.set_face_detector(Detector(.99))
    faces = manager._detect_faces(frame)
    small = dict(faces[0], w=.1, h=.1, confidence=.1)
    best, quality, error = manager._evaluate_faces(frame, [small, faces[0]])
    assert best is faces[0]
    assert error is None
    assert quality['thresholds']['min_detection_confidence'] == .85


def test_clipped_face_uses_actual_crop_size(frame):
    manager = FaceEnrollmentManager()
    manager.set_face_detector(Detector(.99))
    face = dict(manager._detect_faces(frame)[0], x=-.5)
    _, quality, _ = manager._evaluate_faces(frame, [face])
    assert quality['reason'] == 'face_too_small'
    assert quality['metrics']['face_width_px'] == 60


def test_upload_rejection_logged(frame, caplog):
    manager = FaceEnrollmentManager()
    manager.set_face_detector(Detector())
    with caplog.at_level('INFO'):
        manager._prepare_uploaded_face(image_bytes(frame))
    assert 'low_detection_confidence' in caplog.text
    assert '0.85' in caplog.text
