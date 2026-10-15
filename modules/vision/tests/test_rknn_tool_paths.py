from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


VISION = Path(__file__).resolve().parents[1]
ROOT = VISION.parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, VISION / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name,option,suffix", [
    ("check_hand_rknn", "model_dir", Path()),
    ("check_pose_rknn", "model", Path("yolov8n-pose-fp16.rknn")),
])
@pytest.mark.parametrize("override", ["checkout", "shared", "vision"])
def test_model_defaults_follow_deployment_paths(monkeypatch, tmp_path, name, option, suffix, override):
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    monkeypatch.delenv("MARSDOG_VISION_MODEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    expected = ROOT / "models" / "vision"
    if override in ("shared", "vision"):
        monkeypatch.setenv("MARSDOG_MODEL_DIR", str(tmp_path / "shared"))
        expected = tmp_path / "shared" / "vision"
    if override == "vision":
        monkeypatch.setenv("MARSDOG_VISION_MODEL_DIR", str(tmp_path / "specific"))
        expected = tmp_path / "specific"
    args = load_tool(name)._parser().parse_args([])
    assert getattr(args, option) == expected / suffix


@pytest.mark.parametrize("name,flag,option", [
    ("check_hand_rknn", "--model-dir", "model_dir"),
    ("check_pose_rknn", "--model", "model"),
])
def test_explicit_model_argument_wins(monkeypatch, tmp_path, name, flag, option):
    monkeypatch.setenv("MARSDOG_VISION_MODEL_DIR", str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"
    args = load_tool(name)._parser().parse_args([flag, str(explicit)])
    assert getattr(args, option) == explicit


def test_face_defaults_are_independent_of_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    args = load_tool("check_face_rknn")._parser().parse_args([])
    assert args.config == VISION / "config/vision.yaml"
    assert args.images == VISION / "data/faces"


@pytest.mark.parametrize("backend", ["rknn", "mediapipe"])
@pytest.mark.parametrize("unready", [None, "pose", "hand"])
def test_face_pipeline_uses_backend_readiness(monkeypatch, tmp_path, backend, unready):
    import sys
    from types import SimpleNamespace

    import numpy as np

    tool = load_tool("check_face_rknn")
    stopped = []

    class Vision:
        available = True
        face_model_status = {"detect": {"ready": True}, "recognize": {"ready": True}}
        pose_model_status = {"ready": unready != "pose", "backend": backend}
        hand_model_status = {"ready": unready != "hand", "backend": backend}
        # RKNN does not populate the legacy MediaPipe landmarker attributes.
        _pose_landmarker = object() if backend == "mediapipe" else None
        _hand_landmarker = object() if backend == "mediapipe" else None

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            stopped.append("vision")

        def sync_enrolled_to_throttle(self):
            pass

        def run_inference_exclusive(self, callback):
            return callback()

        def _process_frame_impl(self, frame):
            return {"faces": [object()]}

    class Objects:
        last_error = ""

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            stopped.append("objects")

        def detect_objects(self, frame):
            pass

    prefix = "marsdog_vision_interaction.providers."
    monkeypatch.setitem(sys.modules, prefix + "vision_observation", SimpleNamespace(VisionObservationProvider=Vision))
    monkeypatch.setitem(sys.modules, prefix + "object_detector", SimpleNamespace(ObjectDetectorProvider=Objects))
    config = {"providers": {"vision": {"config": {}}, "object": {"config": {}}}}
    frame = np.zeros((16, 16, 3), np.uint8)
    if unready:
        with pytest.raises(AssertionError):
            tool.pipeline_smoke(config, tmp_path, frame, 1)
    else:
        result = tool.pipeline_smoke(config, tmp_path, frame, 1)
        assert result["vision"]["iterations"] == result["yoloe"]["iterations"] == 1
    assert stopped == ["vision", "objects"]
