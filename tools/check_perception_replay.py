"""Run module-owned CPU replay checks in their independent Python environments."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from runtime_environment import ROOT, clean_environment

HEX = re.compile(r"[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[a-zA-Z0-9_-]{1,64}")
ENTRYPOINTS = {"vision": "marsdog_vision_interaction.replay",
               "voice": "marsdog_voice_interaction.replay"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mapping(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(label + " has invalid or unsupported fields")
    return value


def finite_number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(label + " is outside its allowed range")
    return value


def preflight(manifest):
    """Resolve and hash assets without importing model runtimes or touching devices."""
    data = json.loads(manifest.read_text())
    mapping(data, {"schema_version", "description", "vision", "voice"}, "manifest")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if not any(name in data for name in ENTRYPOINTS):
        raise ValueError("Select at least one of vision or voice")
    assets, errors, requests = [], [], {}
    def asset(spec, label, suffixes=None):
        mapping(spec, {"path", "sha256"}, label)
        raw = spec.get("path")
        expected = spec.get("sha256", "")
        if not isinstance(raw, str) or not raw.strip() or not isinstance(expected, str) or not HEX.fullmatch(expected):
            raise ValueError(label + " requires path and lowercase SHA256")
        path = Path(raw).expanduser()
        path = (manifest.parent / path).resolve() if not path.is_absolute() else path.resolve()
        if suffixes and path.suffix.lower() not in suffixes:
            raise ValueError(label + " has unsupported format")
        record = {"name": label, "path": str(path), "expected_sha256": expected}
        if not path.is_file():
            record["status"] = "MISSING"
            errors.append({"code": "MISSING_ASSET", "asset": label, "path": str(path)})
        else:
            actual = sha256(path)
            record.update(sha256=actual, bytes=path.stat().st_size,
                          status="VERIFIED" if actual == expected else "MISMATCH")
            if actual != expected:
                errors.append({"code": "HASH_MISMATCH", "asset": label, "path": str(path)})
        assets.append(record)
        return str(path)
    for name in ENTRYPOINTS:
        if name not in data:
            continue
        section = mapping(data[name],
            {"model", "samples", "settings"} if name == "vision" else
            {"model", "tokens", "model_type", "language", "num_threads", "command_catalog", "samples"}, name)
        request = {"module": name}
        request["model"] = asset(section.get("model"), name + ".model",
                                {".onnx", ".pt"} if name == "vision" else {".onnx"})
        if name == "voice":
            request["tokens"] = asset(section.get("tokens"), "voice.tokens", {".txt"})
            request["model_type"] = section.get("model_type", "sense_voice")
            request["language"] = section.get("language", "zh")
            if request["model_type"] not in ("sense_voice", "paraformer"):
                raise ValueError("Unsupported ASR model_type")
            if request["language"] not in ("zh", "en", "ja", "ko", "yue", "auto"):
                raise ValueError("Unsupported ASR language")
            request["num_threads"] = finite_number(section.get("num_threads", 2), 1, 16, "num_threads")
            if type(request["num_threads"]) is not int:
                raise ValueError("num_threads must be an integer")
            catalog = ROOT / "modules/voice/config/command_catalog.yaml"
            request["command_catalog"] = asset(section.get("command_catalog", {
                "path": str(catalog), "sha256": sha256(catalog)}), "voice.command_catalog", {".yaml", ".yml"})
        else:
            settings = mapping(section.get("settings", {}), {"image_size", "confidence", "iou", "max_detections"}, "vision.settings")
            request["settings"] = {
                "image_size": finite_number(settings.get("image_size", 640), 32, 2048, "image_size"),
                "confidence": finite_number(settings.get("confidence", 0.2), 0.01, 1, "confidence"),
                "iou": finite_number(settings.get("iou", 0.2), 0.01, 1, "iou"),
                "max_detections": finite_number(settings.get("max_detections", 50), 1, 1000, "max_detections")}
            if any(type(request["settings"][k]) is not int for k in ("image_size", "max_detections")):
                raise ValueError("image_size and max_detections must be integers")
        samples = section.get("samples")
        if not isinstance(samples, list) or not 1 <= len(samples) <= 256:
            raise ValueError(name + " requires 1..256 annotated samples")
        request["samples"], ids = [], set()
        for sample in samples:
            allowed = {"id", "image", "expected_labels", "expected_empty"} if name == "vision" else {"id", "audio", "expected_text", "expected_event_type"}
            mapping(sample, allowed, name + ".sample")
            sample_id = sample.get("id")
            if not isinstance(sample_id, str) or not IDENTIFIER.fullmatch(sample_id) or sample_id in ids:
                raise ValueError("Sample ids must be unique simple identifiers")
            ids.add(sample_id)
            item = {"id": sample_id}
            kind = "image" if name == "vision" else "audio"
            item[kind] = asset(sample.get(kind), name + "." + sample_id,
                {".jpg", ".jpeg", ".png", ".bmp"} if name == "vision" else {".wav"})
            if name == "vision":
                labels = sample.get("expected_labels", [])
                empty = sample.get("expected_empty", False)
                if type(empty) is not bool or not isinstance(labels, list) or any(not isinstance(x, str) or not x.strip() for x in labels):
                    raise ValueError("Invalid detection annotation")
                if (empty and labels) or (not empty and not labels):
                    raise ValueError("Provide expected_labels OR expected_empty=true")
                item.update(expected_labels=labels, expected_empty=empty)
            else:
                text = sample.get("expected_text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Voice samples require a nonempty expected_text")
                item["expected_text"] = text
                event = sample.get("expected_event_type")
                if event is not None:
                    if not isinstance(event, str) or not event.startswith("EVT_VOICE_"):
                        raise ValueError("Invalid expected_event_type")
                    item["expected_event_type"] = event
            request["samples"].append(item)
        requests[name] = request
    status = ("FAIL" if any(e["code"] != "MISSING_ASSET" for e in errors) else
              "BLOCKED_MISSING_ASSETS" if errors else "READY")
    return {"status": status, "assets": assets, "errors": errors, "requests": requests,
            "inference_executed": False}


def run_module(name, request, directory, timeout):
    request_path, report_path = directory / (name + "-request.json"), directory / (name + ".json")
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    env = clean_environment()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "modules" / name),
               CUDA_VISIBLE_DEVICES="", YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true",
               YOLO_CONFIG_DIR=str(directory / "ultralytics"), OMP_NUM_THREADS="2")
    command = [str(ROOT / "modules" / name / ".venv/bin/python"), "-B", "-m", ENTRYPOINTS[name],
               "--request", str(request_path), "--output", str(report_path)]
    with (directory / (name + ".log")).open("w") as log:
        proc = subprocess.Popen(command, cwd=directory, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            raise
    if not report_path.is_file():
        raise RuntimeError(name + " did not produce a report; see its log (exit " + str(code) + ")")
    report = json.loads(report_path.read_text())
    wanted = [sample["id"] for sample in request["samples"]]
    actual = [case.get("id") for case in report.get("cases", [])]
    if (code != 0 or report.get("status") != "PASS" or report.get("device") != "cpu"
            or actual != wanted or not report.get("real_model_inference")
            or any(case.get("status") != "PASS" for case in report.get("cases", []))):
        raise RuntimeError(name + " replay failed; see " + str(report_path))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "out/perception-replay")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be 1..3600 seconds")
    directory = args.output.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(os.getpid()))
    directory.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAIL", "inference_executed": False, "run_directory": str(directory),
              "scope": "Offline model replay only; no ROS publication, microphone, camera or robot"}
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Replay interrupted")
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        manifest = args.manifest.resolve()
        report.update(manifest=str(manifest), manifest_sha256=sha256(manifest))
        prepared = preflight(manifest)
        (directory / "preflight.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n")
        report.update(status=prepared["status"], errors=prepared["errors"], assets=prepared["assets"])
        if prepared["status"] == "READY" and not args.check_only:
            report["modules"] = {}
            for name, request in prepared["requests"].items():
                report["modules"][name] = run_module(name, request, directory, args.timeout)
                report["inference_executed"] = True
            # Refuse acceptance if an input was edited during the run.
            if any(sha256(Path(a["path"])) != a["sha256"] for a in prepared["assets"]):
                raise RuntimeError("An input asset changed during replay")
            report["status"] = "PASS"
        report["model_acceptance"] = report["status"] == "PASS"
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="FAIL", error=str(exc) or type(exc).__name__, model_acceptance=False)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(directory / "result.json"),
                      "model_acceptance": report.get("model_acceptance", False)}, ensure_ascii=False))
    return 0 if report["status"] in ("READY", "PASS") else 2 if report["status"] == "BLOCKED_MISSING_ASSETS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
