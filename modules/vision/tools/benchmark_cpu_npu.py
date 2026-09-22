#!/usr/bin/env python3
"""Collect live-camera CPU/NPU vision performance without saving media.

The command is deliberately an observer.  Start the camera driver and the
vision debug launch separately, then run this tool while the real camera is
showing a fixed scenario.  It subscribes to message metadata only; image bytes,
video and rosbag data are never written.

Examples::

    uv run python tools/benchmark_cpu_npu.py --prepare-config cpu \
        --output-dir test-evidence/cpu
    uv run python tools/benchmark_cpu_npu.py --live-camera --label cpu \
        --duration 120 --output-dir test-evidence/cpu \
        --trace log/vision_trace_current.jsonl
    uv run python tools/benchmark_cpu_npu.py --compare \
        test-evidence/cpu/cpu-*.json test-evidence/npu/npu-*.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping

import psutil
import yaml


PROCESS_MARKERS: dict[str, tuple[str, ...]] = {
    "camera_driver": ("camera_driver",),
    "vision_interaction": ("vision_interaction",),
    "vision_debug_viewer": ("vision_debug_viewer",),
}
_NPU_LOAD_RE = re.compile(r"^\s*(?P<load>[0-9]+(?:\.[0-9]+)?)@(?P<freq>[0-9]+)Hz")


def percentile(values: Iterable[float], percent: float) -> float | None:
    """Return a linear-interpolated percentile without a NumPy dependency."""

    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percent) / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def summarize(values: Iterable[float]) -> dict[str, float | int | None]:
    """Summarize finite samples for a report."""

    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    return {
        "count": len(clean),
        "mean": sum(clean) / len(clean),
        "p50": percentile(clean, 50.0),
        "p95": percentile(clean, 95.0),
        "max": max(clean),
    }


def parse_npu_load(raw: str) -> dict[str, float | int | None]:
    """Parse Rockchip devfreq values such as ``100@1000000000Hz``."""

    match = _NPU_LOAD_RE.match(str(raw))
    if not match:
        return {"load_percent": None, "frequency_hz": None}
    return {
        "load_percent": float(match.group("load")),
        "frequency_hz": int(match.group("freq")),
    }


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def read_npu_telemetry(sysfs_dir: str | Path) -> dict[str, float | int | None]:
    """Read NPU load/frequency, preserving unavailable telemetry as null."""

    root = Path(sysfs_dir)
    load = parse_npu_load(_read_text(root / "load") or "")
    current = _read_text(root / "cur_freq")
    try:
        load["current_frequency_hz"] = int(current) if current else None
    except ValueError:
        load["current_frequency_hz"] = None
    return load


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_dir(source: Path) -> Path:
    configured = os.environ.get("MARSDOG_VISION_MODEL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = (
        source.parent.parent / "models" / "vision",
        source.parent.parent.parent / "models" / "vision",
    )
    return next((item.resolve() for item in candidates if item.is_dir()), candidates[0].resolve())


def _vision_config(data: Mapping[str, Any]) -> dict[str, Any]:
    providers = data.get("providers", {})
    vision = providers.get("vision", {}) if isinstance(providers, Mapping) else {}
    config = vision.get("config", {}) if isinstance(vision, Mapping) else {}
    if not isinstance(config, dict):
        raise ValueError("providers.vision.config must be a mapping")
    return config


def prepare_config(
    source: str | Path,
    destination: str | Path,
    backend: str,
    *,
    model_dir: str | Path | None = None,
    disable_object: bool = True,
) -> dict[str, Any]:
    """Create an isolated CPU/NPU config without changing production YAML."""

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("source config must be a YAML mapping")
    if backend not in {"cpu", "npu"}:
        raise ValueError("backend must be cpu or npu")

    model_root = Path(model_dir).expanduser().resolve() if model_dir else _model_dir(source_path)
    vision = _vision_config(data)
    if backend == "cpu":
        vision.update({
            "face_detect_model": str(model_root / "face_detection_yunet_2023mar.onnx"),
            "face_recogn_model": str(model_root / "face_recognition_sface_2021dec.onnx"),
            "pose_model_variant": "lite",
            "hand_landmark_model": str(model_root / "hand_landmarker.task"),
            "hand_detect_model": "",
            "hand_rknn": {"preprocessing": "cpu"},
        })
        face_provider = data.get("providers", {}).get("face_recognition", {})
        if isinstance(face_provider, dict) and isinstance(face_provider.get("config"), dict):
            face_provider["config"]["face_recogn_model"] = str(
                model_root / "face_recognition_sface_2021dec.onnx"
            )
    else:
        vision.update({
            "face_detect_model": str(model_root / "face_detection_yunet_2023mar_fp16.rknn"),
            "face_recogn_model": str(model_root / "face_recognition_sface_2021dec_fp16.rknn"),
            "pose_model_variant": "rknn",
            "hand_detect_model": str(model_root / "hand_detector_fp16.rknn"),
            "hand_landmark_model": str(model_root / "hand_landmarks_detector_fp16.rknn"),
            "hand_rknn": {"profile": "hand_fp16", "preprocessing": "rga", "detection_interval": 5},
        })
        face_provider = data.get("providers", {}).get("face_recognition", {})
        if isinstance(face_provider, dict) and isinstance(face_provider.get("config"), dict):
            face_provider["config"]["face_recogn_model"] = str(
                model_root / "face_recognition_sface_2021dec_fp16.rknn"
            )

    if disable_object:
        object_provider = data.get("providers", {}).get("object", {})
        if isinstance(object_provider, dict):
            object_provider["enabled"] = False

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {
        "backend": backend,
        "source": source_path.name,
        "destination": destination_path.name,
        "model_dir": model_root.name,
        "sha256": _sha256(destination_path),
        "object_disabled": bool(disable_object),
    }


def _process_text(process: psutil.Process) -> str:
    try:
        cmdline = " ".join(process.cmdline())
    except (psutil.Error, OSError):
        cmdline = ""
    try:
        name = process.name()
    except (psutil.Error, OSError):
        name = ""
    return f"{name} {cmdline}".lower()


def discover_processes() -> dict[str, list[psutil.Process]]:
    """Find the three processes from the user-provided launch flow."""

    found: dict[str, list[psutil.Process]] = defaultdict(list)
    own_pid = os.getpid()
    for process in psutil.process_iter(["pid"]):
        if process.pid == own_pid:
            continue
        text = _process_text(process)
        for role, markers in PROCESS_MARKERS.items():
            if any(
                re.search(
                    rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])",
                    text,
                )
                for marker in markers
            ):
                found[role].append(process)
    return dict(found)


def sample_processes(
    processes: Mapping[str, list[psutil.Process]],
) -> dict[str, dict[str, Any]]:
    """Sample CPU/RSS for each role; missing processes remain visible."""

    sample: dict[str, dict[str, Any]] = {}
    for role in PROCESS_MARKERS:
        pids: list[int] = []
        cpu_values: list[float] = []
        rss_values: list[int] = []
        for process in processes.get(role, []):
            try:
                if not process.is_running():
                    continue
                pids.append(process.pid)
                cpu_values.append(float(process.cpu_percent(interval=None)))
                rss_values.append(int(process.memory_info().rss))
            except (psutil.Error, OSError):
                continue
        sample[role] = {
            "pids": pids,
            "cpu_percent": sum(cpu_values) if cpu_values else None,
            "rss_bytes": sum(rss_values) if rss_values else None,
        }
    aggregate_cpu = [
        item["cpu_percent"] for item in sample.values()
        if item["cpu_percent"] is not None
    ]
    aggregate_rss = [
        item["rss_bytes"] for item in sample.values()
        if item["rss_bytes"] is not None
    ]
    sample["aggregate"] = {
        "pids": [pid for item in sample.values() for pid in item.get("pids", [])],
        "cpu_percent": sum(aggregate_cpu) if aggregate_cpu else None,
        "rss_bytes": sum(aggregate_rss) if aggregate_rss else None,
    }
    return sample


def _stats_from_samples(samples: list[dict[str, Any]], field: str) -> dict[str, Any]:
    return summarize(
        float(item[field])
        for item in samples
        if item.get(field) is not None
    )


def summarize_process_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in (*PROCESS_MARKERS.keys(), "aggregate"):
        role_samples = [item.get("processes", {}).get(role, {}) for item in samples]
        result[role] = {
            "cpu_percent": _stats_from_samples(role_samples, "cpu_percent"),
            "rss_bytes": _stats_from_samples(role_samples, "rss_bytes"),
            "last_pids": next(
                (item.get("pids", []) for item in reversed(role_samples) if item.get("pids")),
                [],
            ),
        }
    return result


def _git_metadata(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = run("status", "--short") or ""
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(status), "status_count": len(status.splitlines())}


def _runtime_metadata(root: Path) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent_system": psutil.cpu_percent(interval=None),
        "memory_total_bytes": psutil.virtual_memory().total,
        "git": _git_metadata(root),
    }


def _parse_trace(path: Path, start_epoch: float) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}
    for line in lines:
        if not line.startswith("VISION_TRACE "):
            continue
        try:
            payload = json.loads(line.removeprefix("VISION_TRACE "))
            stamp = datetime.fromisoformat(str(payload["timestamp"])).timestamp()
            if stamp < start_epoch or payload.get("record") != "stage_complete":
                continue
            key = f"{payload.get('module', '')}:{payload.get('stage', '')}"
            values[key].append(float(payload["latency_ms"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return {key: summarize(items) for key, items in sorted(values.items())}


def _load_ros():
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        from std_msgs.msg import String
    except ImportError as exc:  # pragma: no cover - depends on board ROS env
        raise RuntimeError(
            "ROS2 Python modules are unavailable; source /opt/ros/humble/setup.bash first"
        ) from exc
    return rclpy, Node, Image, String, HistoryPolicy, QoSProfile, ReliabilityPolicy


def monitor_live(args: argparse.Namespace) -> dict[str, Any]:
    """Observe the already-running real camera and vision launch."""

    (
        rclpy,
        Node,
        Image,
        String,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    ) = _load_ros()
    start_epoch = time.time()
    resource_samples: list[dict[str, Any]] = []
    npu_samples: list[dict[str, Any]] = []
    processes: dict[str, list[psutil.Process]] = {}
    camera_count = 0
    visual_count = 0
    invalid_event_timestamps = 0
    event_delays: list[float] = []
    camera_stamps: list[float] = []

    class Collector(Node):
        def __init__(self) -> None:
            super().__init__("vision_performance_collector")
            camera_qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
            )
            visual_qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=5,
            )
            self.create_subscription(
                Image, args.camera_topic, self.camera_callback, camera_qos
            )
            self.create_subscription(
                String, args.visual_topic, self.visual_callback, visual_qos
            )

        def camera_callback(self, message: Any) -> None:
            nonlocal camera_count
            camera_count += 1
            stamp = getattr(getattr(message, "header", None), "stamp", None)
            if stamp is not None:
                value = float(getattr(stamp, "sec", 0)) + float(getattr(stamp, "nanosec", 0)) * 1e-9
                if value > 0.0:
                    camera_stamps.append(value)

        def visual_callback(self, message: Any) -> None:
            nonlocal visual_count, invalid_event_timestamps
            visual_count += 1
            try:
                payload = json.loads(str(message.data))
                stamp = float(payload["header"]["stamp"])
                delay = time.time() - stamp
                if not math.isfinite(delay) or delay < 0.0:
                    invalid_event_timestamps += 1
                    return
                event_delays.append(delay * 1000.0)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                invalid_event_timestamps += 1

    rclpy.init()
    node = Collector()
    ready_deadline = time.monotonic() + max(1.0, float(args.startup_timeout))
    ready = False
    try:
        while time.monotonic() < ready_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            processes = discover_processes()
            if processes.get("camera_driver") and processes.get("vision_interaction") and camera_count:
                ready = True
                break
        if not ready:
            return {
                "status": "failed",
                "failure": "camera_driver, vision_interaction, or camera messages were not detected",
                "metadata": _runtime_metadata(Path.cwd()),
                "privacy": {"media_saved": False, "rosbag_saved": False},
            }

        camera_count = 0
        visual_count = 0
        invalid_event_timestamps = 0
        event_delays.clear()
        camera_stamps.clear()
        measurement_start = time.monotonic()
        measurement_epoch = time.time()
        warmup_deadline = measurement_start + max(0.0, float(args.warmup_seconds))
        end_deadline = warmup_deadline + max(1.0, float(args.duration))
        next_sample = time.monotonic()
        while time.monotonic() < end_deadline:
            rclpy.spin_once(node, timeout_sec=0.02)
            now = time.monotonic()
            if now < warmup_deadline:
                next_sample = now
                continue
            if now >= next_sample:
                processes = discover_processes()
                resource_samples.append({
                    "monotonic": now,
                    "processes": sample_processes(processes),
                })
                npu_samples.append({"monotonic": now, **read_npu_telemetry(args.npu_sysfs)})
                next_sample = now + max(0.02, float(args.sample_interval))
        measurement_end = time.time()
    finally:
        node.destroy_node()
        rclpy.shutdown()

    elapsed = max(0.001, measurement_end - measurement_epoch)
    report = {
        "status": "ok",
        "label": args.label,
        "scenario": args.scenario,
        "duration_seconds": elapsed,
        "metadata": _runtime_metadata(Path.cwd()),
        "camera": {
            "topic": args.camera_topic,
            "messages": camera_count,
            "rate_hz": camera_count / elapsed,
            "first_stamp": min(camera_stamps) if camera_stamps else None,
            "last_stamp": max(camera_stamps) if camera_stamps else None,
        },
        "visual_event": {
            "topic": args.visual_topic,
            "messages": visual_count,
            "rate_hz": visual_count / elapsed,
            "capture_to_receipt_ms": summarize(event_delays),
            "invalid_timestamp_count": invalid_event_timestamps,
        },
        "resources": {
            "sample_interval_seconds": float(args.sample_interval),
            "samples": len(resource_samples),
            "processes": summarize_process_samples(resource_samples),
            "npu": {
                "load_percent": summarize(
                    item["load_percent"] for item in npu_samples if item.get("load_percent") is not None
                ),
                "frequency_hz": summarize(
                    item["current_frequency_hz"]
                    for item in npu_samples
                    if item.get("current_frequency_hz") is not None
                ),
                "telemetry_path": str(args.npu_sysfs),
            },
        },
        "trace_stages": _parse_trace(Path(args.trace), measurement_epoch) if args.trace else {},
        "privacy": {"media_saved": False, "rosbag_saved": False, "embeddings_saved": False},
    }
    return report


def _metric(report: Mapping[str, Any], *path: str) -> float | None:
    value: Any = report
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    try:
        return float(value) if value is not None and math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def compare_reports(cpu_path: str | Path, npu_path: str | Path) -> dict[str, Any]:
    """Compare aggregate live reports without exposing local media paths."""

    cpu = json.loads(Path(cpu_path).read_text(encoding="utf-8"))
    npu = json.loads(Path(npu_path).read_text(encoding="utf-8"))
    metrics = {
        "camera_to_event_p95_ms": ("visual_event", "capture_to_receipt_ms", "p95"),
        "camera_to_event_mean_ms": ("visual_event", "capture_to_receipt_ms", "mean"),
        "vision_cpu_mean_percent": ("resources", "processes", "vision_interaction", "cpu_percent", "mean"),
        "vision_cpu_p95_percent": ("resources", "processes", "vision_interaction", "cpu_percent", "p95"),
        "vision_rss_mean_bytes": ("resources", "processes", "vision_interaction", "rss_bytes", "mean"),
        "vision_rss_peak_bytes": ("resources", "processes", "vision_interaction", "rss_bytes", "max"),
        "aggregate_cpu_mean_percent": ("resources", "processes", "aggregate", "cpu_percent", "mean"),
        "aggregate_rss_mean_bytes": ("resources", "processes", "aggregate", "rss_bytes", "mean"),
    }
    result: dict[str, Any] = {}
    for name, path in metrics.items():
        cpu_value = _metric(cpu, *path)
        npu_value = _metric(npu, *path)
        delta = None if cpu_value is None or npu_value is None else npu_value - cpu_value
        relative = None if delta is None or cpu_value == 0 else delta / cpu_value * 100.0
        result[name] = {"cpu": cpu_value, "npu": npu_value, "npu_minus_cpu": delta, "relative_percent": relative}
    return {
        "status": "ok",
        "comparison": "controlled_live_ab",
        "cpu_report": Path(cpu_path).name,
        "npu_report": Path(npu_path).name,
        "metrics": result,
        "limitations": [
            "CPU and NPU received live scenes with the same operator schedule, not identical frames.",
            "Object is excluded from the core comparison and must be read from its NPU-only run.",
        ],
        "privacy": {"media_saved": False, "rosbag_saved": False, "embeddings_saved": False},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("test-evidence/performance"))
    parser.add_argument("--label", choices=("cpu", "npu", "production-npu"), default="npu")
    parser.add_argument("--scenario", default="mixed_scene")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup-seconds", type=float, default=5.0)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--camera-topic", default="/camera/camera/color/image_raw")
    parser.add_argument("--visual-topic", default="/perception/visual_event")
    parser.add_argument("--npu-sysfs", default="/sys/class/devfreq/fdab0000.npu")
    parser.add_argument("--trace", default="", help="Existing vision_trace_current.jsonl path")
    parser.add_argument("--live-camera", action="store_true", help="Explicitly document that input is live camera")
    parser.add_argument("--prepare-config", choices=("cpu", "npu"))
    parser.add_argument("--config-source", type=Path, default=Path("config/vision.yaml"))
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--include-object", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("CPU_REPORT", "NPU_REPORT"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.compare:
        result = compare_reports(*args.compare)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        destination = args.output_dir / "cpu-npu-comparison.json"
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(destination), "status": result["status"]}, ensure_ascii=False))
        return 0
    if args.prepare_config:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        destination = args.output_dir / f"vision.{args.prepare_config}.yaml"
        result = prepare_config(
            args.config_source,
            destination,
            args.prepare_config,
            model_dir=args.model_dir,
            disable_object=not args.include_object,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = monitor_live(args)
    destination = args.output_dir / f"{args.label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "status": report.get("status")}, ensure_ascii=False))
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
