from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "tools" / "benchmark_emotion_rknn.py"
SPEC = importlib.util.spec_from_file_location("benchmark_emotion_rknn", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_default_model_directory_uses_platform_vision_path(monkeypatch, tmp_path):
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    monkeypatch.delenv("MARSDOG_VISION_MODEL_DIR", raising=False)
    assert benchmark._default_model_dir() == Path(__file__).parents[3] / "models" / "vision" / "emotion"

    monkeypatch.setenv("MARSDOG_MODEL_DIR", str(tmp_path / "shared-models"))
    assert benchmark._default_model_dir() == tmp_path / "shared-models" / "vision" / "emotion"

    monkeypatch.setenv("MARSDOG_VISION_MODEL_DIR", str(tmp_path / "vision-models"))
    assert benchmark._default_model_dir() == tmp_path / "vision-models" / "emotion"


def test_preprocess_and_output_contract_use_profile_shapes():
    grayscale_profile = benchmark.MODEL_PROFILES["deepface_emotion_rk3588_fp.rknn"]
    grayscale = benchmark._preprocess(np.full((32, 24), 127, dtype=np.uint8), grayscale_profile)
    assert grayscale.shape == (1, 48, 48, 1)
    assert grayscale.dtype == np.float32
    assert np.all(grayscale == 127.0)

    color_profile = benchmark.MODEL_PROFILES["enet_b0_8_best_afew_rk3588_fp.rknn"]
    color = benchmark._preprocess(np.zeros((16, 16, 3), dtype=np.uint8), color_profile)
    assert color.shape == (1, 3, 224, 224)
    assert color.flags.c_contiguous
    assert np.isfinite(color).all()

    outputs = [np.full((1, 7), 1.0 / 7.0, dtype=np.float32)]
    raw, scores = benchmark._normalize_outputs(outputs, grayscale_profile)
    assert raw.shape == (7,)
    assert np.allclose(scores, np.full(7, 1.0 / 7.0))


def test_manifest_rejects_paths_outside_dataset_root(tmp_path):
    manifest = tmp_path / "jaffe" / "metadata" / "manifest_mtcnn_crops.csv"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "sample_id,relative_path,label\nS001,../outside.jpg,happy\n",
        encoding="utf-8",
    )

    records, report = benchmark._manifest_records(tmp_path, "jaffe")

    assert len(records) == 1
    assert records[0]["preflight_status"] == "preflight_failed"
    assert "resolved path escapes data root" in records[0]["preflight_error"]
    assert report["preflight_failed_rows"] == 1
