"""Focused contracts for format-selected face model adapters."""

from __future__ import annotations

import builtins
import sys
import types

import cv2
import numpy as np
import pytest

from marsdog_vision_interaction.providers.face_backends.factory import (
    FaceBackendError,
    RKNNSFaceRecognizer,
    RKNNYuNetDetector,
    SFACE_PROFILE,
    YUNET_PROFILE,
    _core_mask_value,
    _load_rknn,
    _nms_yunet,
    _similarity_transform,
    decode_yunet_outputs,
)
from marsdog_vision_interaction.providers.face_backends import (
    create_face_detector,
    create_face_recognizer,
)


def _tensor_outputs() -> list[np.ndarray]:
    """Return correctly shaped, zero-valued YuNet outputs."""

    sizes = (6400, 1600, 400)
    return (
        [np.zeros((1, size, 1), np.float32) for size in sizes]
        + [np.zeros((1, size, 1), np.float32) for size in sizes]
        + [np.zeros((1, size, 4), np.float32) for size in sizes]
        + [np.zeros((1, size, 10), np.float32) for size in sizes]
    )


def _profile_file(tmp_path, payload: bytes = b"model"):
    path = tmp_path / "model.rknn"
    path.write_bytes(payload)
    return path


def test_suffix_routing_and_unsupported_formats(monkeypatch, tmp_path):
    detector = object()
    recognizer = object()
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory.OpenCVFaceDetector",
        lambda *args, **kwargs: detector,
    )
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory.OpenCVSFaceRecognizer",
        lambda *args, **kwargs: recognizer,
    )
    assert create_face_detector(tmp_path / "face.ONNX") is detector
    assert create_face_recognizer(tmp_path / "face.onnx") is recognizer
    with pytest.raises(FaceBackendError, match=r"expected \.onnx or \.rknn"):
        create_face_detector(tmp_path / "face.tflite")
    with pytest.raises(FaceBackendError, match=r"expected \.onnx or \.rknn"):
        create_face_recognizer(tmp_path / "face")


def test_profile_fingerprint_rejects_unknown_and_int8_before_runtime(monkeypatch, tmp_path):
    path = _profile_file(tmp_path)
    imported = []

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "rknnlite" or name.startswith("rknnlite."):
            imported.append(name)
            raise AssertionError("runtime must not load for an unverified artifact")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory._sha256_file",
        lambda _: "unknown",
    )
    with pytest.raises(FaceBackendError, match="Unverified RKNN"):
        RKNNYuNetDetector(
            path,
            score_threshold=.3,
            nms_threshold=.45,
            top_k=5000,
            rknn_config={"profile": YUNET_PROFILE},
            runtime_library="",
        )
    assert not imported


def test_wrong_role_profile_is_rejected_before_runtime_import(monkeypatch, tmp_path):
    path = _profile_file(tmp_path)
    real_import = builtins.__import__
    imported = []

    def guarded_import(name, *args, **kwargs):
        if name == "rknnlite" or name.startswith("rknnlite."):
            imported.append(name)
            raise AssertionError("wrong-role profile must fail before runtime import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory._sha256_file",
        lambda _: "unused",
    )
    with pytest.raises(FaceBackendError, match="Unsupported RKNN detector profile"):
        RKNNYuNetDetector(
            path,
            score_threshold=.3,
            nms_threshold=.45,
            top_k=5000,
            rknn_config={"profile": SFACE_PROFILE},
            runtime_library="",
        )
    assert not imported


def _install_rknn_stub(monkeypatch, tmp_path, runtime_class):
    package = types.ModuleType("rknnlite")
    package.__file__ = str(tmp_path / "rknnlite" / "__init__.py")
    api = types.ModuleType("rknnlite.api")
    base_runtime = type("RKNNRuntime", (), {})
    api.rknn_lite = types.SimpleNamespace(RKNNRuntime=base_runtime)
    api.RKNNLite = runtime_class
    runtime_module = types.ModuleType("rknnlite.api.rknn_runtime")
    runtime_module.RKNNRuntime = base_runtime
    monkeypatch.setitem(sys.modules, "rknnlite", package)
    monkeypatch.setitem(sys.modules, "rknnlite.api", api)
    monkeypatch.setitem(sys.modules, "rknnlite.api.rknn_runtime", runtime_module)


def test_load_rknn_success_and_core_configuration(monkeypatch, tmp_path):
    path = _profile_file(tmp_path)
    calls = []

    class FakeRKNNLite:
        NPU_CORE_AUTO = 10
        NPU_CORE_0 = 11
        NPU_CORE_1 = 12
        NPU_CORE_2 = 13
        NPU_CORE_0_1 = 14
        NPU_CORE_0_1_2 = 15

        def __init__(self):
            self.released = 0

        def load_rknn(self, value):
            calls.append(("load", value))
            return 0

        def init_runtime(self, **kwargs):
            calls.append(("init", kwargs))
            return 0

        def release(self):
            self.released += 1

    _install_rknn_stub(monkeypatch, tmp_path, FakeRKNNLite)
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory._sha256_file",
        lambda _: __import__(
            "marsdog_vision_interaction.providers.face_backends.factory",
            fromlist=["YUNET_FP16_SHA256"],
        ).YUNET_FP16_SHA256,
    )
    runtime, profile, metadata = _load_rknn(
        path, "detector", {"profile": YUNET_PROFILE, "core_mask": 0}, ""
    )
    assert profile == YUNET_PROFILE
    assert metadata["role"] == "detector"
    assert calls[0] == ("load", str(path))
    assert calls[1] == ("init", {"core_mask": 11})
    runtime.release()
    assert runtime.released == 1


@pytest.mark.parametrize("stage", ["load", "init"])
def test_load_rknn_failure_releases_partial_context(monkeypatch, tmp_path, stage):
    path = _profile_file(tmp_path)
    instances = []

    class FakeRKNNLite:
        NPU_CORE_AUTO = 10
        NPU_CORE_0 = 11
        NPU_CORE_1 = 12
        NPU_CORE_2 = 13
        NPU_CORE_0_1 = 14
        NPU_CORE_0_1_2 = 15

        def __init__(self):
            self.released = 0
            instances.append(self)

        def load_rknn(self, value):
            return 1 if stage == "load" else 0

        def init_runtime(self, **kwargs):
            return 1 if stage == "init" else 0

        def release(self):
            self.released += 1

    _install_rknn_stub(monkeypatch, tmp_path, FakeRKNNLite)
    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.face_backends.factory._sha256_file",
        lambda _: "bbdd709d9f3385c45e7bb4ac667609866d32f3e80767c1bb0a6c2b4b00e52315",
    )
    with pytest.raises(FaceBackendError, match="failed"):
        _load_rknn(path, "detector", {"profile": YUNET_PROFILE}, "")
    assert len(instances) == 1
    assert instances[0].released == 1


def test_core_mask_rejects_numeric_combined_masks():
    class Constants:
        NPU_CORE_AUTO = "auto"
        NPU_CORE_0 = "core0"
        NPU_CORE_1 = "core1"
        NPU_CORE_2 = "core2"
        NPU_CORE_0_1 = "core01"
        NPU_CORE_0_1_2 = "core012"

    assert _core_mask_value(Constants, 0) == "core0"
    assert _core_mask_value(Constants, 1) == "core1"
    assert _core_mask_value(Constants, 2) == "core2"
    assert _core_mask_value(Constants, "0_1") == "core01"
    assert _core_mask_value(Constants, "0_1_2") == "core012"
    for value in (True, False, 3, 7, "3", "7"):
        with pytest.raises(FaceBackendError):
            _core_mask_value(Constants, value)


def test_yunet_nms_suppresses_overlap_and_honors_top_k():
    rows = np.zeros((3, 15), np.float32)
    rows[:, :4] = [[0, 0, 20, 20], [2, 2, 20, 20], [100, 100, 10, 10]]
    rows[:, 14] = [.9, .8, .7]
    all_kept = _nms_yunet(rows, .3, .45, 0)
    one_kept = _nms_yunet(rows, .3, .45, 1)
    assert len(all_kept) == 2
    assert len(one_kept) == 1
    assert one_kept[0, 14] == pytest.approx(.9)


def test_yunet_decoder_clamps_padding_and_applies_score_formula():
    outputs = _tensor_outputs()
    # One stride-8 detection centred near (100, 50), with a 40x24 box.
    outputs[0][0, 6 * 80 + 12, 0] = 0.81
    outputs[3][0, 6 * 80 + 12, 0] = 0.64
    outputs[6][0, 6 * 80 + 12] = [.5, .25, np.log(40 / 8), np.log(24 / 8)]
    outputs[9][0, 6 * 80 + 12] = [2.5, 1.5, 7.0, 1.5, 5.0, 4.5, 3.5, 7.0, 6.5, 7.0]
    faces = decode_yunet_outputs(
        outputs,
        score_threshold=.3,
        nms_threshold=.45,
        valid_width=640,
        valid_height=480,
    )
    assert faces.shape == (1, 15)
    assert faces[0, 0] == pytest.approx(80.0, abs=1e-4)
    assert faces[0, 1] == pytest.approx(38.0, abs=1e-4)
    assert faces[0, 2] == pytest.approx(40.0, abs=1e-4)
    assert faces[0, 3] == pytest.approx(24.0, abs=1e-4)
    assert faces[0, 14] == pytest.approx(np.sqrt(.81 * .64), abs=1e-6)

    # The same candidate translated wholly into the bottom zero pad is gone.
    outputs[6][0, 6 * 80 + 12] = [12.5 - 2.5, 75.0 - 1.5, np.log(40 / 8), np.log(24 / 8)]
    assert decode_yunet_outputs(outputs, valid_width=640, valid_height=480).size == 0


def test_yunet_decoder_maps_asymmetric_resize_and_rejects_degenerate():
    outputs = _tensor_outputs()
    # Source is 200x100, so x scale is 3.2 and y scale is 3.2.  A box on the
    # padded border gets clipped in model coordinates before inverse mapping.
    index = 2 * 80 + 3
    outputs[0][0, index, 0] = 1.0
    outputs[3][0, index, 0] = 1.0
    outputs[6][0, index] = [0.0, 0.0, np.log(8.0), np.log(8.0)]
    faces = decode_yunet_outputs(
        outputs,
        valid_width=640,
        valid_height=320,
        scale_x=3.2,
        scale_y=3.2,
    )
    assert faces.shape == (1, 15)
    assert faces[0, 0] == pytest.approx(0.0)
    assert faces[0, 1] == pytest.approx(0.0)
    assert faces[0, 2] > 0 and faces[0, 3] > 0


def test_sface_alignment_matches_opencv_similarity_matrix():
    canonical = np.array(
        [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
         [41.5493, 92.3655], [70.7299, 92.2041]],
        dtype=np.float64,
    )
    known_linear = np.array([[0.22, -0.03], [0.03, 0.22]], dtype=np.float64)
    known_translation = np.array([37.0, 8.0], dtype=np.float64)
    landmarks = ((canonical - known_translation) @ np.linalg.inv(known_linear).T).astype(np.float32)
    matrix = _similarity_transform(landmarks)
    projected = np.column_stack((landmarks, np.ones(5))) @ matrix.T
    np.testing.assert_allclose(projected, canonical, atol=1e-4)

    image = np.arange(120 * 140 * 3, dtype=np.uint8).reshape(120, 140, 3)
    ours = cv2.warpAffine(image, matrix, (112, 112), flags=cv2.INTER_LINEAR)
    assert ours.shape == (112, 112, 3)
    with pytest.raises(ValueError, match="degenerate"):
        _similarity_transform(np.zeros((5, 2), np.float32))


class _FakeRuntime:
    def __init__(self, outputs=None, error=None):
        self.outputs = outputs
        self.error = error
        self.release_count = 0
        self.calls = []

    def inference(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.outputs

    def release(self):
        self.release_count += 1


def test_rknn_inference_contract_and_failure_release(monkeypatch):
    runtime = _FakeRuntime(outputs=_tensor_outputs())
    detector = RKNNYuNetDetector.__new__(RKNNYuNetDetector)
    # Bypass artifact loading: this test is about the adapter contract.
    from marsdog_vision_interaction.providers.face_backends.factory import _RuntimeAdapter

    _RuntimeAdapter.__init__(detector, runtime, YUNET_PROFILE)
    detector._score_threshold = .3
    detector._nms_threshold = .45
    detector._top_k = 5000
    detector._source_size = (640, 480)
    _, faces = detector.detect(np.zeros((480, 640, 3), np.uint8))
    assert faces is None
    kwargs = runtime.calls[0]
    assert kwargs["data_format"] == ["nhwc"]
    assert kwargs["inputs_pass_through"] == [1]
    assert kwargs["inputs"][0].dtype == np.float16
    assert kwargs["inputs"][0].shape == (1, 640, 640, 3)
    detector.close()
    assert runtime.release_count == 1

    bad_runtime = _FakeRuntime(error=RuntimeError("inference failed"))
    bad = RKNNYuNetDetector.__new__(RKNNYuNetDetector)
    _RuntimeAdapter.__init__(bad, bad_runtime, YUNET_PROFILE)
    bad._score_threshold = .3
    bad._nms_threshold = .45
    bad._top_k = 5000
    bad._source_size = (640, 480)
    with pytest.raises(RuntimeError, match="inference failed"):
        bad.detect(np.zeros((480, 640, 3), np.uint8))
    assert bad_runtime.release_count == 1

    malformed_runtime = _FakeRuntime(outputs=None)
    malformed = RKNNYuNetDetector.__new__(RKNNYuNetDetector)
    _RuntimeAdapter.__init__(malformed, malformed_runtime, YUNET_PROFILE)
    malformed._score_threshold = .3
    malformed._nms_threshold = .45
    malformed._top_k = 5000
    malformed._source_size = (640, 480)
    with pytest.raises(FaceBackendError, match="YuNet inference returned"):
        malformed.detect(np.zeros((480, 640, 3), np.uint8))
    assert malformed_runtime.release_count == 1
    with pytest.raises(FaceBackendError, match="closed"):
        malformed.detect(np.zeros((480, 640, 3), np.uint8))
    assert malformed_runtime.release_count == 1


def test_sface_feature_is_rgb_float16_nhwc_and_shape_checked():
    runtime = _FakeRuntime(outputs=[np.arange(128, dtype=np.float16).reshape(1, 128)])
    recognizer = RKNNSFaceRecognizer.__new__(RKNNSFaceRecognizer)
    from marsdog_vision_interaction.providers.face_backends.factory import _RuntimeAdapter

    _RuntimeAdapter.__init__(recognizer, runtime, SFACE_PROFILE)
    bgr = np.zeros((37, 49, 3), np.uint8)
    bgr[:, :, 0] = 11
    bgr[:, :, 1] = 22
    bgr[:, :, 2] = 33
    feature = recognizer.feature(bgr)
    assert feature.shape == (1, 128)
    tensor = runtime.calls[0]["inputs"][0]
    assert tensor.shape == (1, 112, 112, 3)
    assert tensor.dtype == np.float16
    assert tensor[0, 0, 0].tolist() == [33.0, 22.0, 11.0]
    recognizer.close()
    assert runtime.release_count == 1
