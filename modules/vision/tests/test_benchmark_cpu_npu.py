from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "benchmark_cpu_npu.py"
SPEC = importlib.util.spec_from_file_location("benchmark_cpu_npu", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_percentile_and_summary_are_stable():
    assert benchmark.percentile([1, 2, 3, 4], 50) == 2.5
    assert benchmark.summarize([1, 2, 3]) == {
        "count": 3,
        "mean": 2.0,
        "p50": 2.0,
        "p95": 2.9,
        "max": 3.0,
    }
    assert benchmark.summarize([])["count"] == 0


def test_parse_npu_load_preserves_invalid_as_unavailable():
    assert benchmark.parse_npu_load("100@1000000000Hz") == {
        "load_percent": 100.0,
        "frequency_hz": 1000000000,
    }
    assert benchmark.parse_npu_load("not-a-load") == {
        "load_percent": None,
        "frequency_hz": None,
    }


def test_prepare_config_does_not_modify_source(tmp_path):
    source = tmp_path / "vision.yaml"
    source.write_text(
        """
providers:
  vision:
    config:
      face_detect_model: old.onnx
      face_recogn_model: old.onnx
      pose_model_variant: lite
      hand_landmark_model: old.task
  object:
    enabled: true
  face_recognition:
    config:
      face_recogn_model: old.onnx
""",
        encoding="utf-8",
    )
    original = source.read_bytes()
    destination = tmp_path / "out" / "vision.cpu.yaml"
    result = benchmark.prepare_config(source, destination, "cpu", model_dir=tmp_path / "models")
    assert source.read_bytes() == original
    assert result["backend"] == "cpu"
    payload = json.loads(json.dumps(__import__("yaml").safe_load(destination.read_text())))
    assert payload["providers"]["vision"]["config"]["pose_model_variant"] == "lite"
    assert payload["providers"]["object"]["enabled"] is False
    assert payload["providers"]["vision"]["config"]["face_detect_model"].endswith(".onnx")


def test_compare_reports_calculates_deltas_without_media(tmp_path):
    template = {
        "visual_event": {"capture_to_receipt_ms": {"mean": 10.0, "p95": 15.0}},
        "resources": {
            "processes": {
                "vision_interaction": {
                    "cpu_percent": {"mean": 80.0, "p95": 90.0},
                    "rss_bytes": {"mean": 100.0, "max": 110.0},
                },
                "aggregate": {
                    "cpu_percent": {"mean": 90.0},
                    "rss_bytes": {"mean": 120.0},
                },
            }
        },
    }
    cpu = tmp_path / "cpu.json"
    npu = tmp_path / "npu.json"
    cpu.write_text(json.dumps(template), encoding="utf-8")
    npu_payload = json.loads(json.dumps(template))
    npu_payload["visual_event"]["capture_to_receipt_ms"]["p95"] = 5.0
    npu_payload["resources"]["processes"]["vision_interaction"]["cpu_percent"]["mean"] = 20.0
    npu.write_text(json.dumps(npu_payload), encoding="utf-8")
    result = benchmark.compare_reports(cpu, npu)
    assert result["metrics"]["camera_to_event_p95_ms"]["npu_minus_cpu"] == -10.0
    assert result["metrics"]["vision_cpu_mean_percent"]["relative_percent"] == -75.0
    assert result["privacy"]["rosbag_saved"] is False
