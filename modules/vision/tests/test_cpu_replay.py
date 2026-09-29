"""Replay adapter contracts with explicit model doubles; not model accuracy tests."""
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from marsdog_vision_interaction import replay
from marsdog_vision_interaction.providers.object_detector import ObjectDetectorProvider


def request(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"test-double-only")
    image = tmp_path / "frame.png"
    assert cv2.imwrite(str(image), np.zeros((16, 16, 3), dtype=np.uint8))
    return {"model": str(model), "settings": {"image_size": 640, "confidence": 0.2,
            "iou": 0.2, "max_detections": 50}, "samples": [
                {"id": "frame", "image": str(image), "expected_labels": ["ball"], "expected_empty": False}]}


def install_model_double(monkeypatch, captured, error=False):
    def load(provider):
        def predict(**kwargs):
            captured.update(kwargs)
            if error:
                raise RuntimeError("backend failed")
            return [SimpleNamespace(names={0: "ball"}, boxes=SimpleNamespace(
                xyxyn=np.array([[0.1, 0.2, 0.3, 0.4]]), conf=np.array([0.9]), cls=np.array([0])))]
        provider._model = SimpleNamespace(predict=predict)
        provider._loaded = True
        return True
    monkeypatch.setattr(ObjectDetectorProvider, "_load_model", load)


def test_cpu_replay_preserves_real_provider_box_decoding(tmp_path, monkeypatch):
    captured = {}
    install_model_double(monkeypatch, captured)
    result = replay.replay(request(tmp_path))
    assert result["status"] == "PASS"
    assert captured["device"] == "cpu" and captured["save"] is False
    assert result["cases"][0]["objects"][0]["label"] == "ball"
    assert result["cases"][0]["objects"][0]["x"] == 0.1


def test_backend_error_cannot_pass_as_empty_scene(tmp_path, monkeypatch):
    install_model_double(monkeypatch, {}, error=True)
    data = request(tmp_path)
    data["samples"][0].update(expected_labels=[], expected_empty=True)
    with pytest.raises(RuntimeError, match="backend failed"):
        replay.replay(data)


def test_bad_image_is_rejected_and_provider_stops(tmp_path, monkeypatch):
    data = request(tmp_path)
    from pathlib import Path
    Path(data["samples"][0]["image"]).write_bytes(b"not an image")
    stopped = []
    monkeypatch.setattr(ObjectDetectorProvider, "stop", lambda self: stopped.append(True))
    with pytest.raises(ValueError, match="decode"):
        replay.replay(data)
    assert stopped == [True]


def test_missing_model_never_loads_backend(tmp_path, monkeypatch):
    data = request(tmp_path)
    data["model"] = str(tmp_path / "absent.onnx")
    monkeypatch.setattr(ObjectDetectorProvider, "start", lambda self: pytest.fail("unexpected start"))
    with pytest.raises(ValueError, match="local CPU"):
        replay.replay(data)


@pytest.mark.parametrize("field,value", [("confidence", float("nan")), ("x", -0.1), ("h", 0)])
def test_bad_detection_is_not_an_accepted_prediction(field, value):
    item = dict(x=.1, y=.2, w=.3, h=.4, confidence=.9, center_x=.25, center_y=.4, label="ball")
    item[field] = value
    assert replay.evaluate([item], {"expected_labels": ["ball"], "expected_empty": False})


def test_missing_label_and_unexpected_object_fail():
    assert replay.evaluate([], {"expected_labels": ["ball"], "expected_empty": False})
    assert replay.evaluate([{}], {"expected_labels": [], "expected_empty": True})


def test_cli_failure_is_machine_readable(tmp_path):
    args = tmp_path / "request.json"
    args.write_text(json.dumps({"model": str(tmp_path / "missing.onnx")}))
    output = tmp_path / "result.json"
    assert replay.main(["--request", str(args), "--output", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "FAIL"
