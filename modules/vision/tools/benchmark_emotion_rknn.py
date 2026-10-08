#!/usr/bin/env python3
"""Zero-shot JAFFE/KDEF emotion benchmark for RK3588 RKNN Lite.

This harness evaluates only images named by the two manifests. It intentionally
has no alternate inference backend: a model is considered runnable only after
its source-backed profile passes the three-crop output smoke gate on the local
NPU. See ``--help`` for paths and run controls.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shlex
import shutil
import sys
import time
import traceback
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
from PIL import Image
import psutil


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PROJECT_DIR / "data" / "benchmark" / "emotion_recognition"
PLATFORM_ROOT = PROJECT_DIR.parents[1]
DEFAULT_RESULTS_ROOT = PLATFORM_ROOT / "out" / "vision" / "benchmark" / "emotion_rknn"


def _default_model_dir() -> Path:
    """Resolve emotion weights through the platform's Vision model contract."""

    from marsdog_vision_interaction.utils.model_paths import vision_model_directory

    return vision_model_directory(__file__) / "emotion"

TARGET_LABELS = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]
LABEL_ALIASES = {
    "anger": "angry",
    "angry": "angry",
    "disgust": "disgust",
    "fear": "fear",
    "happiness": "happy",
    "happy": "happy",
    "neutral": "neutral",
    "sadness": "sad",
    "sad": "sad",
    "surprise": "surprise",
    "contempt": "contempt",
}
DATASETS: dict[str, dict[str, Any]] = {
    "jaffe": {
        "manifest": Path("jaffe/metadata/manifest_mtcnn_crops.csv"),
        "crop_dir": Path("jaffe/face_crops/mtcnn"),
        "expected_count": 212,
    },
    "kdef": {
        "manifest": Path("kdef/metadata/manifest_mtcnn_frontal_a.csv"),
        "crop_dir": Path("kdef/face_crops/mtcnn_frontal_a"),
        "expected_count": 488,
    },
}

EMOTIEFF_REPO = "https://github.com/sb-ai-lab/EmotiEffLib"
DEEPFACE_REPO = "https://github.com/serengil/deepface"
# Immutable upstream revisions reviewed for preprocessing, labels and output
# interpretation. An empty revision fails closed.
SOURCE_REVISIONS: dict[str, str] = {
    "emotiefflib": "520a051c64cd191521e5934655314e769a319684",
    "deepface": "59fb092f139f7c38a9c95fba1162702df86aef9d",
}


def _enet_profile(
    *,
    source_name: str,
    filename: str,
    source_model: str,
    side: int,
    labels: Sequence[str],
    mean: Sequence[float],
    std: Sequence[float],
    output_activation: str,
    aux_count: int = 0,
) -> dict[str, Any]:
    return {
        "filename": filename,
        "source": {
            "repository": EMOTIEFF_REPO,
            "revision_key": "emotiefflib",
            "revision": SOURCE_REVISIONS["emotiefflib"],
            "implementation": source_model,
            "reference": f"{EMOTIEFF_REPO}/blob/{SOURCE_REVISIONS['emotiefflib']}/emotiefflib/facial_analysis.py",
        },
        "source_name": source_name,
        "input": {
            "width": side,
            "height": side,
            "channels": 3,
            "layout": "nchw",
            "dtype": "float32",
            "resize": "Pillow bilinear, square resize",
            "channel_order": "RGB",
            "scale": "uint8 / 255.0",
            "mean": list(mean),
            "std": list(std),
            "pass_through": None,
            "pass_through_mode": "RKNN Lite default; no pass-through override",
        },
        "class_labels": list(labels),
        "output_activation": output_activation,
        "output_meaning": "expression logits followed by raw auxiliary values" if aux_count else "expression logits",
        "aux_count": aux_count,
        "output_contract": {
            "tensor_count": 1,
            "vector_width": len(labels) + aux_count,
            "shape": [[1, len(labels) + aux_count]],
            "conversion_guard": "accept only the exact source expression-score width (plus declared MTL auxiliaries); feature embeddings or unknown heads fail closed",
        },
        "contract_status": "verified",
    }


MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "deepface_emotion_rk3588_fp.rknn": {
        "filename": "deepface_emotion_rk3588_fp.rknn",
        "source": {
            "repository": DEEPFACE_REPO,
            "revision_key": "deepface",
            "revision": SOURCE_REVISIONS["deepface"],
            "implementation": "Emotion",
            "reference": f"{DEEPFACE_REPO}/blob/{SOURCE_REVISIONS['deepface']}/deepface/models/demography/tf/Emotion.py",
            "label_reference": f"{DEEPFACE_REPO}/blob/{SOURCE_REVISIONS['deepface']}/deepface/models/demography/DemographyUtils.py",
        },
        "source_name": "DeepFace Emotion",
        "input": {
            "width": 48,
            "height": 48,
            "channels": 1,
            "public_input_channels": 3,
            "layout": "nhwc",
            "dtype": "float32",
            "resize": "OpenCV INTER_LINEAR, square resize",
            "channel_order": "BGR public crop -> grayscale model input; grayscale JAFFE crop is replicated to BGR first",
            "scale": "uint8 unchanged (0..255)",
            "mean": None,
            "std": None,
            "pass_through": None,
            "pass_through_mode": "RKNN Lite default; no pass-through override",
        },
        "class_labels": ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"],
        "output_activation": "probabilities",
        "output_meaning": "seven-way expression probabilities",
        "aux_count": 0,
        "output_contract": {
            "tensor_count": 1,
            "vector_width": 7,
            "shape": [[1, 7]],
            "conversion_guard": "accept only the seven-way source probability head; feature embeddings or unknown heads fail closed",
        },
        "contract_status": "verified",
    },
    "enet_b0_8_best_afew_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib enet_b0_8_best_afew",
        filename="enet_b0_8_best_afew_rk3588_fp.rknn",
        source_model="enet_b0_8_best_afew",
        side=224,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
    ),
    "enet_b0_8_best_vgaf_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib enet_b0_8_best_vgaf",
        filename="enet_b0_8_best_vgaf_rk3588_fp.rknn",
        source_model="enet_b0_8_best_vgaf",
        side=224,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
    ),
    "enet_b0_8_va_mtl_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib enet_b0_8_va_mtl",
        filename="enet_b0_8_va_mtl_rk3588_fp.rknn",
        source_model="enet_b0_8_va_mtl",
        side=224,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
        aux_count=2,
    ),
    "enet_b2_7_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib enet_b2_7",
        filename="enet_b2_7_rk3588_fp.rknn",
        source_model="enet_b2_7",
        side=260,
        labels=["anger", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
    ),
    "enet_b2_8_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib enet_b2_8",
        filename="enet_b2_8_rk3588_fp.rknn",
        source_model="enet_b2_8",
        side=260,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
    ),
    "mbf_va_mtl_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib mbf_va_mtl",
        filename="mbf_va_mtl_rk3588_fp.rknn",
        source_model="mbf_va_mtl",
        side=112,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.5, 0.5, 0.5],
        std=[0.5, 0.5, 0.5],
        output_activation="logits",
        aux_count=2,
    ),
    "mobilevit_va_mtl_rk3588_fp.rknn": _enet_profile(
        source_name="EmotiEffLib mobilevit_va_mtl",
        filename="mobilevit_va_mtl_rk3588_fp.rknn",
        source_model="mobilevit_va_mtl",
        side=224,
        labels=["anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise"],
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        output_activation="logits",
        aux_count=2,
    ),
}

HOST_REFERENCES = {
    "deepface_emotion_rk3588_fp.rknn": {"jaffe": 0.4575, "kdef": 0.5963},
    "enet_b2_7_rk3588_fp.rknn": {"jaffe": 0.5472, "kdef": 0.7684},
}

PREDICTION_FIELDS = [
    "run_id", "model", "dataset", "row_number", "sample_id", "relative_path",
    "true_label", "predicted_label", "confidence", "status", "error",
    "raw_outputs", "class_scores", "aux_outputs",
]
LATENCY_FIELDS = [
    "run_id", "model", "dataset", "phase", "row_number", "sample_id", "status", "error",
    "disk_read_ms", "image_decode_ms", "preprocess_ms", "rknn_api_ms", "postprocess_ms", "memory_total_ms",
]
TIMING_STAGES = ["disk_read_ms", "image_decode_ms", "preprocess_ms", "rknn_api_ms", "postprocess_ms", "memory_total_ms"]


class RknnCallError(RuntimeError):
    """An RKNN Lite API error with its measured wall duration attached."""

    def __init__(self, elapsed_ms: float, cause: Exception) -> None:
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.elapsed_ms = elapsed_ms


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _elapsed_ms(start: int, end: int | None = None) -> float:
    return ((end if end is not None else time.perf_counter_ns()) - start) / 1_000_000.0


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (_read_text(Path("/etc/os-release")) or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _runtime_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("MARSDOG_RKNN_RUNTIME_LIBRARY", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    try:
        import rknnlite

        candidates.append(Path(rknnlite.__file__).resolve().parent / "api" / "librknnrt.so")
    except Exception:
        pass
    candidates.append(Path("/usr/lib/librknnrt.so"))
    return candidates


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _npu_telemetry() -> dict[str, Any]:
    load_paths = [Path("/sys/kernel/debug/rknpu/load"), Path("/sys/class/devfreq/fdab0000.npu/load")]
    frequency_paths = [
        Path("/sys/class/devfreq/fdab0000.npu/cur_freq"),
        Path("/sys/class/devfreq/fdab0000.npu/available_frequencies"),
    ]
    load_readings = {str(path): _read_text(path) for path in load_paths}
    frequency_readings = {str(path): _read_text(path) for path in frequency_paths}
    return {"load_readings": load_readings, "frequency_readings": frequency_readings}


def _measurement_telemetry() -> dict[str, Any]:
    temperatures: list[dict[str, Any]] = []
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        raw = _read_text(path)
        try:
            celsius = int(raw) / 1000.0 if raw is not None else None
        except ValueError:
            celsius = None
        temperatures.append({"zone": str(path.parent), "name": _read_text(path.parent / "type"), "celsius": celsius})
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
    except Exception as exc:
        cpu_percent = None
        cpu_error = _error_text(exc)
    else:
        cpu_error = None
    try:
        memory = psutil.virtual_memory()
        memory_info = {"available_bytes": memory.available, "percent_used": memory.percent}
    except Exception as exc:
        memory_info = {"error": _error_text(exc)}
    try:
        load_average = list(os.getloadavg())
    except (AttributeError, OSError):
        load_average = None
    return {
        "captured_at": datetime.now().astimezone().isoformat(),
        "cpu_percent_sample": cpu_percent,
        "cpu_percent_error": cpu_error,
        "load_average": load_average,
        "memory": memory_info,
        "temperature_zones": temperatures,
        "npu": _npu_telemetry(),
    }


def _telemetry() -> dict[str, Any]:
    model_text = _read_text(Path("/proc/device-tree/model"))
    temperatures: list[dict[str, Any]] = []
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        raw = _read_text(path)
        zone = path.parent
        name = _read_text(zone / "type")
        try:
            value = int(raw) if raw is not None else None
            celsius = value / 1000.0 if value is not None else None
        except ValueError:
            value, celsius = None, None
        temperatures.append({"zone": str(zone), "name": name, "raw": raw, "celsius": celsius})
    try:
        memory = psutil.virtual_memory()
        memory_info = {"total_bytes": memory.total, "available_bytes": memory.available, "percent_used": memory.percent}
    except Exception as exc:
        memory_info = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        load_average = list(os.getloadavg())
    except (AttributeError, OSError):
        load_average = None
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
    except Exception as exc:
        cpu_percent = None
        cpu_error = f"{type(exc).__name__}: {exc}"
    else:
        cpu_error = None
    processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            cpu = info.get("cpu_percent")
            if cpu is None:
                cpu = proc.cpu_percent(interval=None)
            rss = getattr(info.get("memory_info"), "rss", None)
            processes.append({
                "pid": info.get("pid"),
                "name": info.get("name"),
                "cpu_percent": cpu,
                "rss_bytes": rss,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda item: item.get("cpu_percent") or 0.0, reverse=True)
    runtime_candidates = []
    for path in _runtime_candidates():
        try:
            exists = path.is_file()
            runtime_candidates.append({
                "path": str(path.resolve()) if exists else str(path),
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else None,
                "sha256": _sha256(path) if exists else None,
            })
        except OSError as exc:
            runtime_candidates.append({"path": str(path), "exists": False, "error": str(exc)})
    return {
        "board_model": model_text.replace("\x00", "") if model_text else None,
        "os_release": _read_os_release(),
        "system": {
            "uname": platform.uname()._asdict(),
            "architecture": platform.machine(),
            "python": sys.version,
            "python_executable": sys.executable,
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "cpu_percent_sample": cpu_percent,
            "cpu_percent_error": cpu_error,
            "load_average": load_average,
            "memory": memory_info,
            "top_processes_at_capture": processes[:20],
        },
        "temperature_zones": temperatures,
        "npu": _npu_telemetry(),
        "packages": {
            "rknn_toolkit_lite2": _package_version("rknn-toolkit-lite2"),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "pillow": _package_version("Pillow"),
            "psutil": _package_version("psutil"),
        },
        "runtime_library_candidates": runtime_candidates,
    }


def _canonical_label(raw: Any) -> str | None:
    text = str(raw or "").strip().lower()
    return LABEL_ALIASES.get(text)


def _manifest_records(data_root: Path, dataset: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = DATASETS[dataset]
    manifest = data_root / config["manifest"]
    report: dict[str, Any] = {
        "manifest": str(manifest),
        "expected_count": config["expected_count"],
        "manifest_sha256": None,
        "manifest_file_rows": 0,
        "unique_sample_ids": 0,
        "candidate_crop_files_in_configured_directory": None,
        "label_support": {label: 0 for label in TARGET_LABELS},
        "decoded_image_shape_counts": {},
        "decoded_image_dtype_counts": {},
        "issues": [],
        "status": "unavailable",
    }
    try:
        report["manifest_sha256"] = _sha256(manifest)
        crop_dir = data_root / config["crop_dir"]
        try:
            report["candidate_crop_files_in_configured_directory"] = sum(
                1 for path in crop_dir.rglob("*") if path.is_file()
            )
        except OSError as exc:
            report["issues"].append(f"crop directory listing failed: {exc}")
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required_fields = {"sample_id", "relative_path", "label"}
            fields = set(reader.fieldnames or [])
            if not required_fields.issubset(fields):
                raise ValueError(f"manifest missing required columns: {sorted(required_fields - fields)}")
            for row_number, row in enumerate(reader, start=2):
                sample_id = str(row.get("sample_id") or "").strip()
                rel = str(row.get("relative_path") or "").strip()
                raw_label = str(row.get("label") or "").strip()
                label = _canonical_label(raw_label)
                if label not in TARGET_LABELS:
                    label = None
                errors: list[str] = []
                if not sample_id:
                    errors.append("empty sample_id")
                if sample_id in seen_ids and sample_id:
                    errors.append("duplicate sample_id")
                if sample_id:
                    seen_ids.add(sample_id)
                if not rel:
                    errors.append("empty relative_path")
                candidate = (data_root / rel).resolve() if rel else None
                root_resolved = data_root.resolve()
                expected_crop = (data_root / config["crop_dir"]).resolve()
                if candidate is not None:
                    path_allowed = True
                    try:
                        candidate.relative_to(root_resolved)
                    except ValueError:
                        errors.append("resolved path escapes data root")
                        path_allowed = False
                    try:
                        candidate.relative_to(expected_crop)
                    except ValueError:
                        errors.append("path is outside the configured manifest crop directory")
                        path_allowed = False
                    if path_allowed and not candidate.is_file():
                        errors.append("image file does not exist")
                    elif path_allowed:
                        try:
                            if candidate.stat().st_size <= 0:
                                errors.append("image file is empty")
                            else:
                                encoded = np.fromfile(str(candidate), dtype=np.uint8)
                                decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
                                if decoded is None or decoded.size == 0:
                                    errors.append("OpenCV could not decode image")
                                else:
                                    shape_key = "x".join(str(value) for value in decoded.shape)
                                    shape_counts = report["decoded_image_shape_counts"]
                                    shape_counts[shape_key] = shape_counts.get(shape_key, 0) + 1
                                    dtype_key = str(decoded.dtype)
                                    dtype_counts = report["decoded_image_dtype_counts"]
                                    dtype_counts[dtype_key] = dtype_counts.get(dtype_key, 0) + 1
                                    if decoded.dtype != np.uint8:
                                        errors.append(f"unsupported image dtype: {decoded.dtype}; expected uint8 crop")
                        except (OSError, cv2.error, ValueError) as exc:
                            errors.append(f"image validation failed: {type(exc).__name__}: {exc}")
                if label is None:
                    errors.append(f"illegal label: {raw_label!r}")
                else:
                    report["label_support"][label] += 1
                records.append({
                    "dataset": dataset,
                    "row_number": row_number,
                    "sample_id": sample_id,
                    "relative_path": rel,
                    "path": str(candidate) if candidate is not None else "",
                    "true_label": label or raw_label,
                    "label_valid": label is not None,
                    "preflight_status": "ok" if not errors else "preflight_failed",
                    "preflight_error": "; ".join(errors),
                })
        report["manifest_file_rows"] = len(records)
        report["unique_sample_ids"] = len(seen_ids)
        report["status"] = "ok" if all(row["preflight_status"] == "ok" for row in records) else "issues"
        if len(records) != config["expected_count"]:
            report["issues"].append(
                f"manifest row count {len(records)} differs from expected {config['expected_count']}"
            )
            duplicate_rows = sum("duplicate sample_id" in row["preflight_error"] for row in records)
            empty_ids = sum("empty sample_id" in row["preflight_error"] for row in records)
            report["count_difference_details"] = {
                "difference_rows": len(records) - config["expected_count"],
                "duplicate_sample_id_rows": duplicate_rows,
                "empty_sample_id_rows": empty_ids,
                "candidate_crop_files": report["candidate_crop_files_in_configured_directory"],
                "assessment": "All manifest rows are retained. These counts are evidence for the discrepancy; no unverified cause is inferred.",
            }
            report["status"] = "issues"
        report["preflight_failed_rows"] = sum(row["preflight_status"] != "ok" for row in records)
        return records, report
    except Exception as exc:
        report["issues"].append(f"manifest unavailable or invalid: {type(exc).__name__}: {exc}")
        report["preflight_failed_rows"] = 0
        return [], report


def _profile_issue(profile: Mapping[str, Any]) -> str | None:
    source = profile.get("source", {})
    revision_key = str(source.get("revision_key") or "")
    revision = str(SOURCE_REVISIONS.get(revision_key, "") or "").strip()
    if not revision or len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision.lower()):
        return f"official source revision for {revision_key or 'profile'} is not pinned to a 40-character commit SHA"
    if profile.get("contract_status") != "verified":
        return f"source preprocessing/output contract is not marked verified: {profile.get('contract_status')}"
    input_profile = profile.get("input", {})
    if input_profile.get("dtype") not in {"float32", "float16", "uint8", "int8", "int16"}:
        return f"unsupported or unspecified input dtype: {input_profile.get('dtype')!r}"
    if input_profile.get("layout") not in {"nchw", "nhwc"}:
        return f"unsupported or unspecified input layout: {input_profile.get('layout')!r}"
    if profile.get("output_activation") not in {"logits", "probabilities"}:
        return f"unsupported output activation: {profile.get('output_activation')!r}"
    return None


def _read_decode_image(path: Path, timings: dict[str, float | None] | None = None) -> np.ndarray:
    """Read encoded bytes and decode pixels as separately timed operations."""

    stages = timings if timings is not None else {}
    read_start = time.perf_counter_ns()
    try:
        encoded = path.read_bytes()
    finally:
        stages["disk_read_ms"] = _elapsed_ms(read_start)
    decode_start = time.perf_counter_ns()
    try:
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.size == 0:
            raise ValueError(f"could not decode image: {path}")
        return image
    finally:
        stages["image_decode_ms"] = _elapsed_ms(decode_start)


def _to_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    if image.ndim != 3:
        raise ValueError(f"expected grayscale or color image, got shape {image.shape}")
    if image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
    raise ValueError(f"unsupported channel count: {image.shape}")


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim != 3:
        raise ValueError(f"expected grayscale or color image, got shape {image.shape}")
    if image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise ValueError(f"unsupported channel count: {image.shape}")


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3:
        raise ValueError(f"expected grayscale or color image, got shape {image.shape}")
    if image.shape[2] == 3:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    raise ValueError(f"unsupported channel count: {image.shape}")


def _resize_pillow_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(rgb, mode="RGB")
    resampling = getattr(Image, "Resampling", Image).BILINEAR
    return np.asarray(image.resize((width, height), resample=resampling), dtype=np.uint8)


def _preprocess(image: np.ndarray, profile: Mapping[str, Any]) -> np.ndarray:
    spec = profile["input"]
    width, height = int(spec["width"]), int(spec["height"])
    if spec["channels"] == 1:
        if spec["resize"].startswith("OpenCV INTER_LINEAR"):
            # Recreate DeepFace's public BGR image boundary explicitly, even
            # for gray JAFFE crops, then apply the source's BGR->gray conversion.
            bgr = _to_bgr(image)
            plane = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(plane, (width, height), interpolation=cv2.INTER_LINEAR)
        else:
            raise ValueError(f"unsupported grayscale resize rule: {spec['resize']}")
        arr = resized.astype(np.float32)
        scale = spec.get("scale")
        if scale == "uint8 / 255.0":
            arr /= np.float32(255.0)
        elif scale == "uint8 unchanged (0..255)":
            pass
        else:
            raise ValueError(f"unverified grayscale input scale: {scale!r}")
        if spec["layout"] == "nhwc":
            arr = arr[None, :, :, None]
        else:
            arr = arr[None, None, :, :]
    elif spec["channels"] == 3:
        rgb = _to_rgb(image)
        resize_rule = str(spec["resize"])
        if resize_rule.startswith("Pillow bilinear"):
            resized = _resize_pillow_rgb(rgb, width, height)
        else:
            raise ValueError(f"unsupported RGB resize rule: {resize_rule}")
        arr = resized.astype(np.float32) / np.float32(255.0)
        mean = np.asarray(spec.get("mean"), dtype=np.float32).reshape((1, 1, 3))
        std = np.asarray(spec.get("std"), dtype=np.float32).reshape((1, 1, 3))
        if np.any(std == 0.0) or not np.isfinite(mean).all() or not np.isfinite(std).all():
            raise ValueError("invalid source mean/std")
        arr = (arr - mean) / std
        if spec["layout"] == "nchw":
            arr = np.transpose(arr, (2, 0, 1))[None, :, :, :]
        else:
            arr = arr[None, :, :, :]
    else:
        raise ValueError(f"unsupported channel count in profile: {spec['channels']}")
    dtype_name = str(spec["dtype"])
    dtypes = {
        "float32": np.float32,
        "float16": np.float16,
        "uint8": np.uint8,
        "int8": np.int8,
        "int16": np.int16,
    }
    if dtype_name not in dtypes:
        raise ValueError(f"unsupported profile dtype {dtype_name}")
    arr = np.ascontiguousarray(arr.astype(dtypes[dtype_name], copy=False))
    expected = (1, int(spec["channels"]), height, width) if spec["layout"] == "nchw" else (
        1, height, width, int(spec["channels"])
    )
    if arr.shape != expected:
        raise ValueError(f"prepared input shape {arr.shape} does not match profile {expected}")
    if not np.isfinite(arr).all():
        raise ValueError("prepared input contains non-finite values")
    return arr


def _normalize_outputs(outputs: Any, profile: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(outputs, (list, tuple)) or len(outputs) != int(profile["output_contract"]["tensor_count"]):
        got = len(outputs) if isinstance(outputs, (list, tuple)) else type(outputs).__name__
        raise ValueError(f"output tensor count {got} does not match source contract")
    output = np.asarray(outputs[0])
    allowed_shapes = [tuple(shape) for shape in profile["output_contract"]["shape"]]
    if output.shape not in allowed_shapes:
        raise ValueError(f"output shape {output.shape} not in source contract {allowed_shapes}")
    if output.dtype.kind not in "f" or not np.isfinite(output).all():
        raise ValueError(f"output dtype/values are not interpretable floating point: {output.dtype}")
    vector = output.reshape(-1).astype(np.float64)
    expected_width = int(profile["output_contract"]["vector_width"])
    if vector.size != expected_width:
        raise ValueError(f"output width {vector.size} != expected {expected_width}")
    label_count = len(profile["class_labels"])
    class_values = vector[:label_count]
    if profile["output_activation"] == "logits":
        shifted = class_values - np.max(class_values)
        exps = np.exp(shifted)
        scores = exps / np.sum(exps)
    else:
        if np.any(class_values < -1e-5) or np.any(class_values > 1.00001):
            raise ValueError("probability output contains values outside [0,1]")
        total = float(np.sum(class_values))
        if not math.isclose(total, 1.0, rel_tol=0.02, abs_tol=0.02):
            raise ValueError(f"probability output sums to {total:.6g}, not approximately 1")
        scores = class_values
    if not np.isfinite(scores).all():
        raise ValueError("class score calculation produced non-finite values")
    return vector, scores


def _smoke_output_evidence(outputs: Any) -> dict[str, Any]:
    tensors = list(outputs) if isinstance(outputs, (list, tuple)) else [outputs]
    shapes: list[list[int] | None] = []
    dtypes: list[str | None] = []
    finite_flags: list[bool | None] = []
    numeric: list[dict[str, Any]] = []
    for tensor in tensors:
        try:
            array = np.asarray(tensor)
        except Exception as exc:
            shapes.append(None)
            dtypes.append(None)
            finite_flags.append(None)
            numeric.append({"conversion_error": _error_text(exc)})
            continue
        shapes.append(list(array.shape))
        dtypes.append(str(array.dtype))
        try:
            finite_mask = np.isfinite(array)
            finite = bool(finite_mask.all())
            finite_values = np.asarray(array[finite_mask], dtype=np.float64)
        except TypeError:
            finite, finite_values = False, np.asarray([], dtype=np.float64)
        finite_flags.append(finite)
        item: dict[str, Any] = {
            "min_finite": float(np.min(finite_values)) if finite_values.size else None,
            "max_finite": float(np.max(finite_values)) if finite_values.size else None,
            "mean_finite": float(np.mean(finite_values)) if finite_values.size else None,
        }
        if array.size <= 64:
            item["values"] = array.tolist() if finite else None
        else:
            item["values_omitted_reason"] = "tensor has more than 64 values; finite min/max/mean retained"
        numeric.append(item)
    return {
        "output_container_type": type(outputs).__name__,
        "output_count": len(outputs) if isinstance(outputs, (list, tuple)) else None,
        "output_shapes": shapes,
        "output_dtypes": dtypes,
        "output_finite": finite_flags,
        "output_numeric": numeric,
    }


def _record_latency(
    run_id: str,
    model: str,
    dataset: str,
    phase: str,
    sample: Mapping[str, Any] | None,
    status: str,
    error: str | None,
    stages: Mapping[str, float | None],
) -> dict[str, Any]:
    row = {field: None for field in LATENCY_FIELDS}
    row.update({
        "run_id": run_id,
        "model": model,
        "dataset": dataset,
        "phase": phase,
        "row_number": sample.get("row_number") if sample else "",
        "sample_id": sample.get("sample_id") if sample else "",
        "status": status,
        "error": error or "",
    })
    for key in TIMING_STAGES:
        row[key] = stages.get(key)
    return row


def _prediction_placeholder(run_id: str, model: str, sample: Mapping[str, Any], status: str = "pending", error: str = "") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "model": model,
        "dataset": sample["dataset"],
        "row_number": sample["row_number"],
        "sample_id": sample["sample_id"],
        "relative_path": sample["relative_path"],
        "true_label": sample["true_label"],
        "predicted_label": "FAILED" if status not in {"pending", "ok"} else "",
        "confidence": None,
        "status": status,
        "error": error,
        "raw_outputs": None,
        "class_scores": None,
        "aux_outputs": None,
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# RK3588 emotion RKNN benchmark",
        "",
        f"- Run ID: `{summary.get('run_id')}`",
        f"- Status: **{summary.get('run_status')}**",
        "- Scope: already-cropped manifest face images only; no face detection, camera capture, or camera end-to-end timing.",
        "- NPU inference timing is RKNN Lite API wall time, including input staging and output retrieval.",
        "- FPS = successful predictions / summed successful in-memory total time; file read and decode are excluded.",
        "- Percentiles use NumPy linear interpolation; standard deviation is population standard deviation.",
        "- File reads and image decoding are timed separately. Preflight/hash reads can warm the OS page cache, so disk-read times are not cold-storage latency.",
        "",
        "## Environment",
        "",
        f"- Board: {summary.get('environment', {}).get('board_model')}",
        f"- OS: {summary.get('environment', {}).get('os_release', {}).get('PRETTY_NAME')}",
        f"- Kernel: {summary.get('environment', {}).get('system', {}).get('uname', {}).get('release')}",
        f"- Python: {summary.get('environment', {}).get('system', {}).get('python')}",
        f"- RKNN Lite: {summary.get('environment', {}).get('packages', {}).get('rknn_toolkit_lite2')}",
        f"- Core: `{summary.get('npu_configuration', {}).get('core_selection')}` → `{summary.get('npu_configuration', {}).get('core_mask_constant')}`; `target=None`; batch size 1.",
        "",
        "## Dataset preflight",
        "",
        "| Dataset | Manifest rows | Expected | Unique IDs | Preflight failures | Crop files in configured directory |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for dataset, item in summary.get("datasets", {}).items():
        lines.append(
            f"| {dataset} | {item.get('manifest_file_rows', 0)} | {item.get('expected_count')} | "
            f"{item.get('unique_sample_ids', 0)} | {item.get('preflight_failed_rows', 0)} | "
            f"{item.get('candidate_crop_files_in_configured_directory')} |"
        )
    lines += ["", "## Model × dataset summary", "", "| Model | Dataset | Status | Coverage | Accuracy | Macro-F1 | Balanced accuracy | NPU API p50 ms | NPU API p95 ms | In-memory FPS |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    pairs = summary.get("model_dataset", {})
    for key in sorted(pairs):
        item = pairs[key]
        latency = item.get("latency", {}).get("rknn_api_ms", {})
        metrics = item.get("metrics", {}).get("all_manifest", {})
        lines.append(
            f"| {item.get('model')} | {item.get('dataset')} | {item.get('status')} | "
            f"{item.get('coverage', {}).get('successful')}/{item.get('coverage', {}).get('manifest_rows')} "
            f"({item.get('coverage', {}).get('rate')}) | {metrics.get('accuracy')} | "
            f"{metrics.get('macro_f1')} | {metrics.get('balanced_accuracy')} | "
            f"{latency.get('p50')} | {latency.get('p95')} | "
            f"{item.get('in_memory_throughput_fps', {}).get('fps')} |"
        )
    lines += ["", "Host-reference comparisons", ""]
    compared = False
    for key in sorted(pairs):
        comparison = pairs[key].get("host_reference_comparison")
        if comparison is None:
            continue
        compared = True
        lines.append(
            f"- {pairs[key].get('model')} / {pairs[key].get('dataset')}: host accuracy "
            f"{comparison.get('host_accuracy')}, board accuracy {comparison.get('board_accuracy')}, "
            f"difference {comparison.get('difference_percentage_points')} percentage points. "
            f"{comparison.get('interpretation')}"
        )
    if not compared:
        lines.append("No host-reference model/dataset pair had an accuracy result.")
    for dataset in DATASETS:
        lines += ["", f"## {dataset.upper()} per-class metrics and confusion matrices", ""]
        for key in sorted(k for k in pairs if pairs[k].get("dataset") == dataset):
            item = pairs[key]
            metrics = item.get("metrics", {}).get("all_manifest", {})
            lines += [f"### {item.get('model')} — {item.get('status')}", ""]
            if item.get("error"):
                lines += [f"Error: `{item['error']}`", ""]
            per_class = metrics.get("per_class", {})
            lines += ["| Class | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"]
            for label in TARGET_LABELS:
                item_class = per_class.get(label, {})
                lines.append(
                    f"| {label} | {item_class.get('precision')} | {item_class.get('recall')} | "
                    f"{item_class.get('f1')} | {item_class.get('support')} |"
                )
            confusion = metrics.get("confusion_matrix", {})
            columns = confusion.get("columns", [])
            matrix = confusion.get("matrix", [])
            lines += ["", f"Confusion matrix columns: `{columns}`", "", "| True \\ Predicted | " + " | ".join(columns) + " |", "|---|" + "---:|" * len(columns)]
            for label, values in zip(confusion.get("rows", []), matrix):
                lines.append(f"| {label} | " + " | ".join(str(value) for value in values) + " |")
            success = item.get("metrics", {}).get("successful_only")
            lines += ["", f"Successful-only metrics: `{_safe_json(success)}`", ""]
    lines += ["", "## Model source profiles and timing", ""]
    for model, item in summary.get("models", {}).items():
        smoke_summary = [
            {
                key: smoke.get(key)
                for key in (
                    "dataset", "sample_id", "input_shape", "input_dtype",
                    "output_shapes", "output_dtypes", "output_finite",
                    "output_numeric", "output_finite_contract_check",
                    "class_score_sum", "prediction", "contract_error", "inference_error",
                )
            }
            for smoke in item.get("smoke", [])
        ]
        lines += [
            f"### {model}",
            "",
            f"- Source profile: {item.get('profile', {}).get('source_name')}",
            f"- Source revision: {item.get('profile', {}).get('source', {}).get('revision')}",
            f"- Status: {item.get('status')}",
            f"- SHA-256: `{item.get('sha256')}`",
            f"- File load ms: {item.get('load_ms')}",
            f"- Runtime init ms: {item.get('runtime_init_ms')}",
            f"- First inference ms: {item.get('first_inference_ms')}",
            f"- Warm-up calls: {item.get('warmup_count')}",
            f"- Input contract evidence: {item.get('input_contract_validation')}",
            f"- Input profile: `{_safe_json(item.get('profile', {}).get('input'))}`",
            f"- Output contract: `{_safe_json(item.get('profile', {}).get('output_contract'))}`",
            f"- Smoke checks: `{_safe_json(smoke_summary)}`",
            "",
        ]
        if item.get("error"):
            lines.append(f"Failure: `{item['error']}`")
            lines.append("")
    lines += ["## Errors and anomalies", ""]
    errors = summary.get("errors", [])
    if not errors:
        lines.append("No recorded errors.")
    else:
        lines.extend(f"- `{error}`" for error in errors)
    lines += ["", "## Reproduction", "", f"- Command: `{summary.get('reproduction', {}).get('command')}`", "- The exact script copy is `benchmark_emotion_rknn.py`; RKNN output is captured in `rknn_runtime.log`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _latency_summary(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(v) for v in values if math.isfinite(float(v))]
    if not clean:
        result: dict[str, Any] = {"count": 0, "mean": None, "median": None, "p50": None, "p95": None, "p99": None, "stddev_population": None}
    else:
        arr = np.asarray(clean, dtype=np.float64)
        result = {
            "count": int(arr.size),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "p50": float(np.percentile(arr, 50, method="linear")),
            "p95": float(np.percentile(arr, 95, method="linear")),
            "p99": float(np.percentile(arr, 99, method="linear")),
            "stddev_population": float(np.std(arr, ddof=0)),
        }
    return result


def _compute_metrics(
    samples: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    predicted_columns = list(TARGET_LABELS)
    if "contempt" in [LABEL_ALIASES.get(str(label).lower(), str(label).lower()) for label in profile["class_labels"]]:
        predicted_columns.append("contempt")
    predicted_columns.append("FAILED")
    matrix = np.zeros((len(TARGET_LABELS), len(predicted_columns)), dtype=np.int64)
    lookup = {label: index for index, label in enumerate(predicted_columns)}
    valid_truth_rows = 0
    invalid_truth_rows = 0
    all_correct = 0
    successful_truth_rows = 0
    successful_correct = 0
    successful_matrix = np.zeros_like(matrix)
    pred_by_key = {(str(p["dataset"]), int(p["row_number"])): p for p in predictions}
    for sample in samples:
        truth = _canonical_label(sample.get("true_label"))
        prediction = pred_by_key.get((str(sample["dataset"]), int(sample["row_number"])), {})
        status = prediction.get("status")
        predicted = prediction.get("predicted_label") if status == "ok" else "FAILED"
        if truth not in TARGET_LABELS:
            invalid_truth_rows += 1
            continue
        valid_truth_rows += 1
        col = lookup.get(str(predicted), lookup["FAILED"])
        row = TARGET_LABELS.index(truth)
        matrix[row, col] += 1
        if status == "ok":
            successful_truth_rows += 1
            successful_matrix[row, col] += 1
            if predicted == truth:
                successful_correct += 1
                all_correct += 1
        # failed rows, contempt, and other labels remain incorrect.
    def metrics_from_matrix(cm: np.ndarray, denom: int, correct: int) -> dict[str, Any]:
        per_class: dict[str, Any] = {}
        recalls: list[float] = []
        f1_values: list[float] = []
        for idx, label in enumerate(TARGET_LABELS):
            tp = int(cm[idx, idx])
            support = int(cm[idx, :].sum())
            predicted_count = int(cm[:, idx].sum())
            recall = tp / support if support else None
            precision = tp / predicted_count if predicted_count else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if recall is not None and precision + recall > 0 else 0.0 if recall is not None else None
            per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
            if recall is not None:
                recalls.append(recall)
            if f1 is not None:
                f1_values.append(f1)
        return {
            "accuracy": correct / denom if denom else None,
            "macro_f1": float(np.mean(f1_values)) if f1_values else None,
            "balanced_accuracy": float(np.mean(recalls)) if recalls else None,
            "denominator_valid_truth": denom,
            "correct": correct,
            "per_class": per_class,
            "confusion_matrix": {
                "rows": list(TARGET_LABELS),
                "columns": predicted_columns,
                "matrix": cm.tolist(),
            },
        }
    all_metrics = metrics_from_matrix(matrix, valid_truth_rows, all_correct)
    success_metrics = metrics_from_matrix(successful_matrix, successful_truth_rows, successful_correct)
    return {
        "all_manifest": all_metrics,
        "successful_only": success_metrics,
        "invalid_truth_rows_excluded_from_class_metrics": invalid_truth_rows,
    }


def _make_pair_summary(
    model: str,
    dataset: str,
    samples: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    latency_rows: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    model_status: str,
    model_error: str | None,
) -> dict[str, Any]:
    subset = [p for p in predictions if p["model"] == model and p["dataset"] == dataset]
    ds_samples = [s for s in samples if s["dataset"] == dataset]
    successful = [p for p in subset if p.get("status") == "ok"]
    measured = [row for row in latency_rows if row["model"] == model and row["dataset"] == dataset and row["phase"] == "full"]
    timings: dict[str, Any] = {}
    for stage in TIMING_STAGES:
        vals = [float(row[stage]) for row in measured if row.get(stage) not in (None, "")]
        timings[stage] = _latency_summary(vals)
    in_memory_total_seconds = sum(
        float(p["_memory_total_ms"])
        for p in successful
        if p.get("_memory_total_ms") is not None
    ) / 1000.0
    in_memory_fps = (
        len(successful) / in_memory_total_seconds
        if in_memory_total_seconds > 0
        else None
    )
    rates = len(successful) / len(ds_samples) if ds_samples else None
    pair_status = "ok" if len(successful) == len(ds_samples) and model_status == "ok" else (
        "partial" if successful else (model_status if model_status != "ok" else "failed")
    )
    metrics = _compute_metrics(ds_samples, subset, profile)
    if model_status != "ok" and not successful:
        metrics["status"] = "unavailable_model_gate_failed"
        metrics["reason"] = model_error or "model did not pass its load/runtime/smoke gate"
        for metric_set in (metrics["all_manifest"], metrics["successful_only"]):
            for field in ("accuracy", "macro_f1", "balanced_accuracy"):
                metric_set[field] = None
            for per_class in metric_set["per_class"].values():
                per_class["precision"] = None
                per_class["recall"] = None
                per_class["f1"] = None
    else:
        metrics["status"] = "available"
    host = HOST_REFERENCES.get(model, {}).get(dataset)
    board_accuracy = metrics["all_manifest"].get("accuracy")
    host_comparison = None
    if host is not None:
        host_comparison = {
            "host_accuracy": host,
            "board_accuracy": board_accuracy,
            "difference_percentage_points": (board_accuracy - host) * 100.0 if board_accuracy is not None else None,
            "interpretation": "Large gaps can reflect dataset/crop selection, preprocessing or conversion/runtime parity, and numeric differences; the host score is a reference, not a target.",
        }
    return {
        "model": model,
        "dataset": dataset,
        "status": pair_status,
        "error": model_error,
        "coverage": {
            "manifest_rows": len(ds_samples),
            "successful": len(successful),
            "failed_or_pending": len(ds_samples) - len(successful),
            "rate": rates,
        },
        "metrics": metrics,
        "latency": timings,
        "in_memory_throughput_fps": {
            "fps": in_memory_fps,
            "successful_predictions": len(successful),
            "successful_in_memory_total_seconds": in_memory_total_seconds,
            "disk_decode_excluded": True,
        },
        "host_reference_comparison": host_comparison,
    }


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _load_and_prepare(sample: Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, float]]:
    stages: dict[str, float | None] = {}
    image = _read_decode_image(Path(str(sample["path"])), stages)
    start = time.perf_counter_ns()
    prepared = _preprocess(image, profile)
    stages["preprocess_ms"] = _elapsed_ms(start)
    return prepared, {key: float(value) for key, value in stages.items() if value is not None}


def _run_rknn_call(runtime: Any, input_tensor: np.ndarray, profile: Mapping[str, Any]) -> tuple[Any, float]:
    spec = profile["input"]
    start = time.perf_counter_ns()
    try:
        outputs = runtime.inference(
            inputs=[input_tensor],
            data_type=str(spec["dtype"]),
            data_format=str(spec["layout"]),
            inputs_pass_through=[int(spec["pass_through"])] if spec.get("pass_through") is not None else None,
        )
    except Exception as exc:
        raise RknnCallError(_elapsed_ms(start), exc) from exc
    return outputs, _elapsed_ms(start)


def _make_result(prediction: dict[str, Any], raw: np.ndarray, scores: np.ndarray, profile: Mapping[str, Any]) -> None:
    labels = [LABEL_ALIASES.get(str(label).lower(), str(label).lower()) for label in profile["class_labels"]]
    index = int(np.argmax(scores))
    prediction.update({
        "predicted_label": labels[index],
        "confidence": float(scores[index]),
        "status": "ok",
        "error": "",
        "raw_outputs": _safe_json(raw.tolist()),
        "class_scores": _safe_json({label: float(score) for label, score in zip(labels, scores.tolist())}),
        "aux_outputs": _safe_json({f"aux_{i}": float(value) for i, value in enumerate(raw[len(labels):])}) if profile.get("aux_count") else None,
    })


def _initial_summary(run_id: str, command: str, data_root: Path, model_dir: Path, output_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "run_status": "running",
        "created_at_local": datetime.now().astimezone().isoformat(),
        "scope": "manifest-listed face crops only; no face detection, camera capture, or camera end-to-end timing",
        "npu_configuration": {
            "target": None,
            "batch_size": 1,
            "core_selection": "0_1_2",
            "core_mask_constant": None,
            "core_constant_name": "RKNNLite.NPU_CORE_0_1_2",
            "cpu_fallback": False,
        },
        "paths": {"data_root": str(data_root), "model_dir": str(model_dir), "output_dir": str(output_dir)},
        "reproduction": {
            "command": command,
            "script": "benchmark_emotion_rknn.py",
            "runtime_log": "rknn_runtime.log",
            "python_executable": sys.executable,
            "warmup_count_requested": 20,
            "smoke_inference_count_requested": 3,
            "percentile_method": "NumPy percentile(method='linear')",
            "disk_timing_definition": "disk_read_ms times encoded file reads; image_decode_ms times OpenCV decoding; both are outside in-memory total",
            "in_memory_total_definition": "wall time around preprocessing + RKNN Lite API call + postprocessing; excludes disk read and image decode",
            "rknn_api_timing_definition": "RKNN Lite inference API wall time including input staging and output retrieval; not isolated kernel time",
            "fps_definition": "successful predictions divided by summed successful in-memory total seconds; file read and decode excluded",
            "preflight_reads_may_warm_page_cache": True,
        },
        "environment": {},
        "source_revisions": SOURCE_REVISIONS,
        "datasets": {},
        "models": {},
        "model_dataset": {},
        "errors": [],
    }


def _refresh_pairs(summary: dict[str, Any], samples_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]], predictions: Sequence[Mapping[str, Any]], latency_rows: Sequence[Mapping[str, Any]]) -> None:
    for model, model_info in summary["models"].items():
        for dataset in DATASETS:
            # Prediction placeholders are initialized from each full manifest
            # before any model is run, so they also serve as the durable sample
            # index while producing incremental reports.
            sample_map: dict[int, dict[str, Any]] = {}
            for row in predictions:
                if row.get("model") == model and row.get("dataset") == dataset:
                    sample_map[int(row["row_number"])] = {
                        "dataset": dataset,
                        "row_number": int(row["row_number"]),
                        "true_label": row.get("true_label"),
                    }
            samples = list(sample_map.values())
            pair = _make_pair_summary(
                model, dataset, samples, predictions, latency_rows,
                model_info.get("profile", MODEL_PROFILES[model]),
                model_info.get("status", "pending"), model_info.get("error"),
            )
            summary["model_dataset"][f"{model}::{dataset}"] = pair


def _persist(
    output_dir: Path,
    summary: dict[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    latency_rows: Sequence[Mapping[str, Any]],
) -> None:
    _refresh_pairs(summary, {}, predictions, latency_rows)
    _write_json(output_dir / "summary.json", summary)
    _write_csv(output_dir / "predictions.csv", PREDICTION_FIELDS, predictions)
    _write_csv(output_dir / "latency.csv", LATENCY_FIELDS, latency_rows)
    _write_report(output_dir / "report.md", summary)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="emotion model directory (defaults to the platform Vision model directory/emotion)",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", default="", help="optional run directory name; must not already exist")
    parser.add_argument("--warmups", type=int, default=20, help="warm-up inference count per successful model (minimum 20)")
    return parser.parse_args(argv)


def _unique_output_dir(root: Path, requested_run_id: str) -> tuple[str, Path]:
    run_id = requested_run_id.strip() or datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise ValueError("run-id must be a single safe directory name")
    destination = root / run_id
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    return run_id, destination


def _source_profile_metadata(profile: Mapping[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(profile))
    source = copied.get("source", {})
    revision_key = source.get("revision_key")
    if revision_key:
        source["revision"] = SOURCE_REVISIONS.get(revision_key, "")
    return copied


def _install_runtime_log(output_dir: Path) -> tuple[Any, int, int, Any, Any, Any, Any]:
    stream = (output_dir / "rknn_runtime.log").open("a", encoding="utf-8", buffering=1)
    old_stdout, old_stderr = os.dup(1), os.dup(2)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    os.dup2(stream.fileno(), 1)
    os.dup2(stream.fileno(), 2)
    sys.stdout = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    sys.stderr = os.fdopen(os.dup(2), "w", encoding="utf-8", buffering=1)
    return stream, old_stdout, old_stderr, original_stdout, original_stderr, sys.stdout, sys.stderr


def _restore_runtime_log(state: tuple[Any, int, int, Any, Any, Any, Any]) -> None:
    stream, old_stdout, old_stderr, original_stdout, original_stderr, redirected_stdout, redirected_stderr = state
    try:
        redirected_stdout.flush()
        redirected_stderr.flush()
    except Exception:
        pass
    sys.stdout, sys.stderr = original_stdout, original_stderr
    redirected_stdout.close()
    redirected_stderr.close()
    os.dup2(old_stdout, 1)
    os.dup2(old_stderr, 2)
    os.close(old_stdout)
    os.close(old_stderr)
    stream.close()


def _model_metadata(path: Path, profile: Mapping[str, Any]) -> dict[str, Any]:
    try:
        exists = path.is_file()
        return {
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else None,
            "sha256": _sha256(path) if exists else None,
            "source_name": profile.get("source_name"),
            "profile": _source_profile_metadata(profile),
            "status": "pending" if exists else "blocked",
            "error": None if exists else f"model file is missing: {path}",
            "load_ms": None,
            "runtime_init_ms": None,
            "first_inference_ms": None,
            "warmup_count": 0,
            "smoke_attempt_count": 0,
            "smoke": [],
            "input_contract_validation": "source-derived contract is passed explicitly; RKNN Lite 2.3.2 exposes no public loaded-model input metadata query, so successful smoke acceptance is recorded as runtime evidence",
        }
    except OSError as exc:
        return {
            "path": str(path), "exists": False, "size_bytes": None, "sha256": None,
            "source_name": profile.get("source_name"), "profile": _source_profile_metadata(profile),
            "status": "blocked", "error": _error_text(exc), "load_ms": None,
            "runtime_init_ms": None, "first_inference_ms": None, "warmup_count": 0, "smoke": [],
            "smoke_attempt_count": 0,
            "input_contract_validation": "source-derived contract is passed explicitly; RKNN Lite 2.3.2 exposes no public loaded-model input metadata query, so successful smoke acceptance is recorded as runtime evidence",
        }


def _failed_prediction_rows(
    run_id: str,
    model: str,
    samples_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    status: str,
    error: str,
) -> list[dict[str, Any]]:
    return [
        _prediction_placeholder(run_id, model, sample, status, error)
        for dataset in DATASETS
        for sample in samples_by_dataset.get(dataset, [])
    ]


def _replace_model_rows(
    predictions: list[dict[str, Any]],
    model_name: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    predictions[:] = [row for row in predictions if row.get("model") != model_name]
    predictions.extend(dict(row) for row in rows)


def _upsert_prediction(predictions: list[dict[str, Any]], row: dict[str, Any]) -> None:
    key = (row["model"], row["dataset"], int(row["row_number"]))
    for index, existing in enumerate(predictions):
        current = (existing.get("model"), existing.get("dataset"), int(existing.get("row_number", -1)))
        if current == key:
            predictions[index] = row
            return
    predictions.append(row)


def _parse_sdk_version(runtime: Any) -> Any:
    try:
        return runtime.get_sdk_version()
    except Exception as exc:
        return {"error": _error_text(exc)}


def _record_full_sample(
    run_id: str,
    model_name: str,
    sample: Mapping[str, Any],
    profile: Mapping[str, Any],
    runtime: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prediction = _prediction_placeholder(run_id, model_name, sample)
    stage: dict[str, float | None] = {key: None for key in TIMING_STAGES}
    memory_start: int | None = None
    try:
        if sample.get("preflight_status") != "ok":
            raise ValueError(f"preflight failed: {sample.get('preflight_error')}")
        image = _read_decode_image(Path(str(sample["path"])), stage)
        memory_start = time.perf_counter_ns()
        preprocess_start = time.perf_counter_ns()
        try:
            tensor = _preprocess(image, profile)
        finally:
            stage["preprocess_ms"] = _elapsed_ms(preprocess_start)
        try:
            outputs, inference_ms = _run_rknn_call(runtime, tensor, profile)
        except RknnCallError as exc:
            stage["rknn_api_ms"] = exc.elapsed_ms
            raise
        stage["rknn_api_ms"] = inference_ms
        post_start = time.perf_counter_ns()
        try:
            raw, scores = _normalize_outputs(outputs, profile)
            _make_result(prediction, raw, scores, profile)
        finally:
            stage["postprocess_ms"] = _elapsed_ms(post_start)
        stage["memory_total_ms"] = _elapsed_ms(memory_start)
    except Exception as exc:
        prediction.update({"predicted_label": "FAILED", "status": "sample_failed", "error": _error_text(exc)})
        if memory_start is not None:
            stage["memory_total_ms"] = _elapsed_ms(memory_start)
    latency = _record_latency(
        run_id, model_name, str(sample["dataset"]), "full", sample,
        "ok" if prediction["status"] == "ok" else str(prediction["status"]),
        prediction.get("error"), stage,
    )
    prediction["_memory_total_ms"] = stage["memory_total_ms"] if prediction["status"] == "ok" else None
    return prediction, latency


def _smoke_sample_order(samples_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    valid = {
        dataset: [sample for sample in samples_by_dataset.get(dataset, []) if sample.get("preflight_status") == "ok"]
        for dataset in DATASETS
    }
    chosen: list[Mapping[str, Any]] = []
    if valid["jaffe"]:
        chosen.append(valid["jaffe"][0])
    if valid["kdef"]:
        chosen.append(valid["kdef"][0])
    if valid["jaffe"] and len(valid["jaffe"]) > 1:
        chosen.append(valid["jaffe"][1])
    elif valid["kdef"] and len(valid["kdef"]) > 1:
        chosen.append(valid["kdef"][1])
    return chosen


def _run_model(
    run_id: str,
    model_name: str,
    model_info: dict[str, Any],
    model_path: Path,
    samples_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    predictions: list[dict[str, Any]],
    latency_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    output_dir: Path,
    warmups: int,
) -> None:
    profile = model_info["profile"]
    model_info["telemetry_before"] = _measurement_telemetry()
    _replace_model_rows(predictions, model_name, [
        _prediction_placeholder(run_id, model_name, sample, "pending")
        for dataset in DATASETS for sample in samples_by_dataset.get(dataset, [])
    ])
    profile_issue = _profile_issue(profile)
    if profile_issue:
        model_info.update({"status": "blocked", "error": profile_issue})
        _replace_model_rows(predictions, model_name, _failed_prediction_rows(run_id, model_name, samples_by_dataset, "profile_blocked", profile_issue))
        summary["errors"].append(f"{model_name}: {profile_issue}")
        model_info["telemetry_after"] = _measurement_telemetry()
        _persist(output_dir, summary, predictions, latency_rows)
        return
    if not model_path.is_file():
        error = f"model file is missing: {model_path}"
        model_info.update({"status": "load_failed", "error": error})
        _replace_model_rows(predictions, model_name, _failed_prediction_rows(run_id, model_name, samples_by_dataset, "model_load_failed", error))
        summary["errors"].append(f"{model_name}: {error}")
        model_info["telemetry_after"] = _measurement_telemetry()
        _persist(output_dir, summary, predictions, latency_rows)
        return
    runtime = None
    try:
        initial_hash = model_info.get("sha256")
        current_hash = _sha256(model_path)
        if current_hash != initial_hash:
            raise RuntimeError(f"model SHA-256 changed after preflight: {initial_hash} -> {current_hash}")
        from marsdog_vision_interaction.utils.rknn_runtime import configure_rknn_runtime

        configure_rknn_runtime("")
        selected_library = next((path.resolve() for path in _runtime_candidates() if path.is_file()), None)
        summary["environment"]["selected_runtime_library"] = str(selected_library) if selected_library else None
        if selected_library is not None:
            summary["environment"]["selected_runtime_library_sha256"] = _sha256(selected_library)
        from rknnlite.api import RKNNLite

        if not hasattr(RKNNLite, "NPU_CORE_0_1_2"):
            raise RuntimeError("installed RKNNLite lacks NPU_CORE_0_1_2")
        core_mask = RKNNLite.NPU_CORE_0_1_2
        summary["npu_configuration"]["core_mask_constant"] = core_mask
        runtime = RKNNLite(verbose=False)
        start = time.perf_counter_ns()
        try:
            load_result = runtime.load_rknn(str(model_path))
        finally:
            model_info["load_ms"] = _elapsed_ms(start)
        if load_result != 0:
            raise RuntimeError(f"load_rknn returned {load_result}")
        start = time.perf_counter_ns()
        try:
            init_result = runtime.init_runtime(target=None, core_mask=core_mask, async_mode=False)
        finally:
            model_info["runtime_init_ms"] = _elapsed_ms(start)
        model_info["target"] = None
        model_info["core_selection"] = "0_1_2"
        model_info["core_mask_constant"] = core_mask
        if init_result != 0:
            raise RuntimeError(f"init_runtime(target=None, core_mask={core_mask}) returned {init_result}")
        model_info["runtime_sdk_version"] = _parse_sdk_version(runtime)
        model_info["runtime_initialized_on_local_npu"] = True

        smoke_samples = _smoke_sample_order(samples_by_dataset)
        if len(smoke_samples) < 3:
            raise RuntimeError(f"need 3 valid manifest crops for smoke check; found {len(smoke_samples)}")
        prepared_smoke: list[tuple[Mapping[str, Any], np.ndarray, dict[str, float]]] = []
        smoke_errors: list[str] = []
        for sample in smoke_samples[:3]:
            try:
                tensor, initial = _load_and_prepare(sample, profile)
                prepared_smoke.append((sample, tensor, initial))
            except Exception as exc:
                smoke_errors.append(f"{sample.get('dataset')}/{sample.get('sample_id')}: {_error_text(exc)}")
                model_info["smoke"].append({
                    "dataset": sample.get("dataset"),
                    "row_number": sample.get("row_number"),
                    "sample_id": sample.get("sample_id"),
                    "preprocessing_error": _error_text(exc),
                })
        if smoke_errors:
            raise RuntimeError("smoke preprocessing failed: " + " | ".join(smoke_errors))
        smoke_results: list[tuple[Mapping[str, Any], np.ndarray, dict[str, float], Any, float, dict[str, Any], dict[str, Any]]] = []
        smoke_call_errors: list[str] = []
        for smoke_index, (sample, tensor, initial) in enumerate(prepared_smoke):
            model_info["smoke_attempt_count"] = int(model_info.get("smoke_attempt_count", 0)) + 1
            try:
                outputs, inference_ms = _run_rknn_call(runtime, tensor, profile)
                if smoke_index == 0:
                    model_info["first_inference_ms"] = inference_ms
                latency_record = _record_latency(
                    run_id, model_name, str(sample["dataset"]),
                    "smoke_first_inference" if smoke_index == 0 else "smoke",
                    sample, "ok", None,
                    {"disk_read_ms": initial.get("disk_read_ms"),
                     "image_decode_ms": initial.get("image_decode_ms"),
                     "preprocess_ms": initial.get("preprocess_ms"),
                     "rknn_api_ms": inference_ms,
                     "memory_total_ms": float(initial.get("preprocess_ms", 0.0)) + inference_ms},
                )
                latency_rows.append(latency_record)
                smoke_record = {
                    "dataset": sample["dataset"],
                    "row_number": sample["row_number"],
                    "sample_id": sample["sample_id"],
                    "input_shape": list(tensor.shape),
                    "input_dtype": str(tensor.dtype),
                    **_smoke_output_evidence(outputs),
                }
                model_info["smoke"].append(smoke_record)
                smoke_results.append((sample, tensor, initial, outputs, inference_ms, latency_record, smoke_record))
            except Exception as exc:
                smoke_call_errors.append(f"{sample.get('dataset')}/{sample.get('sample_id')}: {_error_text(exc)}")
                failed_ms = exc.elapsed_ms if isinstance(exc, RknnCallError) else None
                if smoke_index == 0 and failed_ms is not None:
                    model_info["first_inference_ms"] = failed_ms
                model_info["smoke"].append({
                    "dataset": sample["dataset"],
                    "row_number": sample["row_number"],
                    "sample_id": sample["sample_id"],
                    "input_shape": list(tensor.shape),
                    "input_dtype": str(tensor.dtype),
                    "inference_error": _error_text(exc),
                })
                latency_rows.append(_record_latency(
                    run_id, model_name, str(sample["dataset"]),
                    "smoke_first_inference" if smoke_index == 0 else "smoke",
                    sample, "smoke_inference_failed", _error_text(exc),
                    {"disk_read_ms": initial.get("disk_read_ms"),
                     "image_decode_ms": initial.get("image_decode_ms"),
                     "preprocess_ms": initial.get("preprocess_ms"),
                     "rknn_api_ms": failed_ms,
                     "memory_total_ms": float(initial.get("preprocess_ms", 0.0)) + failed_ms if failed_ms is not None else None},
                ))
        if smoke_call_errors:
            raise RuntimeError("smoke inference failed: " + " | ".join(smoke_call_errors))
        smoke_output_errors: list[str] = []
        for sample, tensor, initial, outputs, inference_ms, latency_record, smoke_record in smoke_results:
            post_start = time.perf_counter_ns()
            try:
                raw, scores = _normalize_outputs(outputs, profile)
                post_ms = _elapsed_ms(post_start)
                class_index = int(np.argmax(scores))
                class_label = str(profile["class_labels"][class_index])
                smoke_record.update({
                    "output_finite_contract_check": bool(np.isfinite(raw).all()),
                    "class_score_sum": float(np.sum(scores)),
                    "prediction": LABEL_ALIASES.get(class_label.lower(), class_label.lower()),
                    "interpreted_raw_outputs": raw.tolist(),
                })
                latency_record["postprocess_ms"] = post_ms
                latency_record["memory_total_ms"] = float(initial.get("preprocess_ms", 0.0)) + inference_ms + post_ms
            except Exception as exc:
                smoke_output_errors.append(f"{sample.get('dataset')}/{sample.get('sample_id')}: {_error_text(exc)}")
                latency_record["status"] = "smoke_output_failed"
                latency_record["error"] = _error_text(exc)
                smoke_record["contract_error"] = _error_text(exc)
        if smoke_output_errors:
            raise RuntimeError("smoke output contract failed: " + " | ".join(smoke_output_errors))
        model_info["smoke_passed"] = True
        warm_sample, warm_tensor, warm_initial = prepared_smoke[0]
        for warm_index in range(warmups):
            try:
                warm_outputs, inference_ms = _run_rknn_call(runtime, warm_tensor, profile)
                if not isinstance(warm_outputs, (list, tuple)) or len(warm_outputs) != int(profile["output_contract"]["tensor_count"]):
                    raise ValueError("warm-up returned no output or an unexpected tensor count")
                status, error = "ok", None
            except Exception as exc:
                inference_ms = exc.elapsed_ms if isinstance(exc, RknnCallError) else None
                status, error = "warmup_failed", _error_text(exc)
            latency_rows.append(_record_latency(
                run_id, model_name, str(warm_sample["dataset"]), "warmup", warm_sample,
                status, error, {"rknn_api_ms": inference_ms},
            ))
            if error:
                raise RuntimeError(f"warm-up {warm_index + 1} failed: {error}")
            model_info["warmup_count"] = int(model_info.get("warmup_count", 0)) + 1
        model_info["status"] = "ok"
        model_info["error"] = None
        _persist(output_dir, summary, predictions, latency_rows)

        for dataset in DATASETS:
            full_count = 0
            for sample in samples_by_dataset.get(dataset, []):
                prediction, latency = _record_full_sample(run_id, model_name, sample, profile, runtime)
                _upsert_prediction(predictions, prediction)
                latency_rows.append(latency)
                if prediction.get("status") != "ok":
                    summary["errors"].append(
                        f"{model_name} {dataset}/{sample.get('sample_id')} row {sample.get('row_number')}: "
                        f"{prediction.get('status')}: {prediction.get('error')}"
                    )
                full_count += 1
                # Keep complete partial evidence even if the process is interrupted.
                if full_count % 50 == 0:
                    _persist(output_dir, summary, predictions, latency_rows)
            _persist(output_dir, summary, predictions, latency_rows)
    except Exception as exc:
        error = _error_text(exc)
        model_info["status"] = "model_failed"
        model_info["error"] = error
        summary["errors"].append(f"{model_name}: {error}")
        # Preserve completed sample rows and mark each untouched placeholder.
        for row in predictions:
            if row.get("model") == model_name and row.get("status") == "pending":
                row.update({"predicted_label": "FAILED", "status": "model_failed", "error": error})
        latency_rows.append(_record_latency(run_id, model_name, "", "model_failure", None, "model_failed", error, {}))
    finally:
        if runtime is not None:
            try:
                runtime.release()
            except Exception as exc:
                summary["errors"].append(f"{model_name}: runtime release failed: {_error_text(exc)}")
        model_info["telemetry_after"] = _measurement_telemetry()
    _persist(output_dir, summary, predictions, latency_rows)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.warmups < 20:
        raise SystemExit("--warmups must be at least 20")
    data_root = args.data_root.expanduser().resolve()
    model_dir = (
        args.model_dir.expanduser().resolve()
        if args.model_dir is not None
        else _default_model_dir()
    )
    results_root = args.results_root.expanduser().resolve()
    run_id, output_dir = _unique_output_dir(results_root, args.run_id)
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
    shutil.copy2(Path(__file__).resolve(), output_dir / "benchmark_emotion_rknn.py")
    (output_dir / "command.txt").write_text(command + "\n", encoding="utf-8")
    log_state = _install_runtime_log(output_dir)
    try:
        print(f"Starting RK3588 emotion benchmark {run_id}", flush=True)
        summary = _initial_summary(run_id, command, data_root, model_dir, output_dir)
        summary["reproduction"]["warmup_count_requested"] = args.warmups
        summary["environment"] = _telemetry()
        summary["npu_configuration"].update({
            "core_selection": "0_1_2",
            "requested_core_constant_name": "RKNNLite.NPU_CORE_0_1_2",
            "target": None,
            "batch_size": 1,
            "warmups": args.warmups,
            "smoke_inferences": 3,
        })
        samples_by_dataset: dict[str, list[dict[str, Any]]] = {}
        for dataset in DATASETS:
            records, report = _manifest_records(data_root, dataset)
            samples_by_dataset[dataset] = records
            summary["datasets"][dataset] = report
            if report["issues"]:
                summary["errors"].extend(f"{dataset}: {issue}" for issue in report["issues"])
        model_names = list(MODEL_PROFILES)
        predictions: list[dict[str, Any]] = []
        latency_rows: list[dict[str, Any]] = []
        for model_name in model_names:
            profile = _source_profile_metadata(MODEL_PROFILES[model_name])
            model_path = model_dir / model_name
            summary["models"][model_name] = _model_metadata(model_path, profile)
        # One row per selected model × manifest row exists from run start; not-yet-run
        # entries are marked pending and are replaced as each model is attempted.
        for model_name in model_names:
            predictions.extend(
                _prediction_placeholder(run_id, model_name, sample, "pending")
                for dataset in DATASETS for sample in samples_by_dataset.get(dataset, [])
            )
        _persist(output_dir, summary, predictions, latency_rows)
        # Use an index so updating an existing pending placeholder never duplicates rows.
        for model_name in model_names:
            _run_model(
                run_id, model_name, summary["models"][model_name], model_dir / model_name,
                samples_by_dataset, predictions, latency_rows, summary, output_dir, args.warmups,
            )
        summary["environment_after"] = _telemetry()
        expected_prediction_rows = sum(len(samples_by_dataset.get(dataset, [])) for dataset in DATASETS) * len(model_names)
        all_attempted = all(summary["models"][name].get("status") != "pending" for name in model_names)
        rows_accounted = len(predictions) == expected_prediction_rows and not any(
            prediction.get("status") == "pending" for prediction in predictions
        )
        execution_complete = all_attempted and rows_accounted
        quality_clean = execution_complete and not summary.get("errors") and all(
            summary["models"][name].get("status") == "ok" for name in model_names
        ) and all(
            summary["datasets"][dataset].get("preflight_failed_rows", 0) == 0
            and summary["datasets"][dataset].get("manifest_file_rows") == DATASETS[dataset]["expected_count"]
            for dataset in DATASETS
        ) and all(
            pair.get("coverage", {}).get("successful") == pair.get("coverage", {}).get("manifest_rows")
            for pair in summary.get("model_dataset", {}).values()
        )
        summary["run_status"] = "complete" if quality_clean else "complete_with_failures" if execution_complete else "incomplete"
        summary["models_requested"] = model_names
        summary["model_dataset_attempts"] = len(model_names) * len(DATASETS)
        summary["prediction_row_count"] = len(predictions)
        summary["latency_row_count"] = len(latency_rows)
        _persist(output_dir, summary, predictions, latency_rows)
        print(f"Run status: {summary['run_status']}; results: {output_dir}", flush=True)
        return 0 if summary["run_status"] in {"complete", "complete_with_failures"} else 2
    except KeyboardInterrupt:
        summary = locals().get("summary")
        if isinstance(summary, dict):
            summary["run_status"] = "interrupted"
            summary.setdefault("errors", []).append("keyboard interrupt; partial evidence retained")
            _persist(output_dir, summary, locals().get("predictions", []), locals().get("latency_rows", []))
        return 130
    except Exception as exc:
        print(f"Fatal harness error: {_error_text(exc)}", flush=True)
        traceback.print_exc()
        summary = locals().get("summary")
        if isinstance(summary, dict):
            summary["run_status"] = "incomplete"
            summary.setdefault("errors", []).append(f"fatal harness error: {_error_text(exc)}")
            _persist(output_dir, summary, locals().get("predictions", []), locals().get("latency_rows", []))
        return 1
    finally:
        _restore_runtime_log(log_state)


if __name__ == "__main__":
    raise SystemExit(main())
