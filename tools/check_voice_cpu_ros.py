"""Isolated installed Voice CPU pipeline gate; no hardware or default profile changes."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from runtime_environment import ROOT, ros_environment
from prepare_cpu_models import sha256, verify, safe_path
from check_perception_replay import preflight


def prepare_request(voice_manifest, intent_manifest, directory, install):
    prepared = preflight(voice_manifest)
    if prepared["status"] != "READY" or set(prepared["requests"]) != {"voice"}:
        raise ValueError("A verified voice-only replay manifest is required")
    voice = prepared["requests"]["voice"]
    if len(voice["samples"]) != 1 or voice["samples"][0]["id"] != "upstream-zh-itn":
        raise ValueError("This probe requires the pinned upstream-zh-itn WAV fixture")
    sample = voice["samples"][0]
    if sample["expected_text"] != "开放时间早上9点至下午5点。":
        raise ValueError("Unexpected transcript annotation for fixed neutral fixture")
    manifest = json.loads(intent_manifest.read_text())
    def resolve(raw):
        path = Path(raw)
        return (intent_manifest.parent / path).resolve() if not path.is_absolute() else path.resolve()
    model = resolve(manifest["model_directory"])
    lock_path = resolve(manifest["model_lock"])
    lock = json.loads(lock_path.read_text())
    assets = {x["path"]: x["sha256"] for x in prepared["assets"]}
    for entry in lock["files"]:
        path = safe_path(model, entry["path"])
        verify(path, entry)
        assets[str(path)] = sha256(path)
    provider = manifest["provider"]
    if provider.get("type") != "qwen_cpu" or not provider.get("enabled"):
        raise ValueError("Explicit Qwen CPU provider is required")
    if Path(provider["config"]["model"]).resolve() != model:
        raise ValueError("Provider differs from verified model directory")
    for path in (voice_manifest, intent_manifest, lock_path):
        assets[str(path.resolve())] = sha256(path)
    request = {
        "install": str(install), "asr": voice, "intent": provider,
        "prefix": "/development/voice_cpu_" + uuid.uuid4().hex,
        "wav_case": {**sample, "source": "qwen_cpu", "expected_tag": "NONE|NONE|NONE",
                     "must_not_execute": True},
    }
    request_path = directory / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    return request_path, assets


def stop_owned_group(process):
    """Reap the observer and surviving descendants, including observer failure."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=5)
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def evaluate_report(data, code):
    integration = (code == 0 and data.get("integration_acceptance") is True
                   and data.get("worker_returncode") == 0
                   and data.get("real_asr_cases") == 1 and data.get("text_fixture_cases") == 4
                   and data.get("after_stop_no_inference") is True
                   and isinstance(data.get("worker", {}).get("pid"), int)
                   and isinstance(data.get("observer_pid"), int)
                   and data["worker"]["pid"] > 0 and data["observer_pid"] > 0
                   and data["worker"]["pid"] != data["observer_pid"])
    expected = ["upstream-zh-itn", "qwen-sit", "qwen-no-sit", "qwen-reject", "catalog-sit"]
    integration = integration and [x.get("id") for x in data.get("cases", [])] == expected
    integration = integration and all(not x["transport_errors"] for x in data.get("cases", []))
    quality = bool(integration and all(not x["quality_errors"] for x in data["cases"]))
    return bool(integration), quality


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-manifest", type=Path,
                        default=ROOT / "out/models/cpu-20260929/voice-replay.json")
    parser.add_argument("--intent-manifest", type=Path,
                        default=ROOT / "out/models/qwen2.5-0.5b-instruct/intent-replay.json")
    parser.add_argument("--output", type=Path, default=ROOT / "out/voice-cpu-ros")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout <= 600:
        parser.error("timeout must be 30..600 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    directory = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir()
    report = {"status": "FAIL", "integration_acceptance": False, "model_acceptance": False,
              "run_directory": str(directory), "domain": 215}
    lock_path = ROOT / "out/voice-cpu-ros/domain215.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    process = None
    def interrupt(signum, frame):
        raise KeyboardInterrupt("CPU ROS probe interrupted")
    old_handlers = {s: signal.signal(s, interrupt) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from marsdog import INSTALL, LOCAL, source_fingerprint
            receipt = json.loads((LOCAL / "build-receipt.json").read_text())
            before = source_fingerprint()
            if receipt["source_sha256"] != before:
                raise RuntimeError("Installed code is stale: run tools/marsdog.py build")
            request, assets = prepare_request(args.voice_manifest.resolve(), args.intent_manifest.resolve(),
                                             directory, INSTALL)
            tool_hash = sha256(Path(__file__))
            report.update(assets_sha256=assets, source_fingerprint=before, tool_sha256=tool_hash)
            env = ros_environment(INSTALL, 215)
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                       ROS_LOG_DIR=str(directory / "ros-log"))
            python = ROOT / "modules/voice/.venv/bin/python"
            env["MARSDOG_PYTHON"] = str(python)
            command = [str(python), "-B", str(ROOT / "modules/voice/tests/ros_cpu_pipeline_probe.py"),
                       "--request", str(request), "--output", str(directory)]
            with (directory / "observer.log").open("w") as log:
                process = subprocess.Popen(command, cwd=directory, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=args.timeout)
                except BaseException:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=25)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                    raise
            data = json.loads((directory / "probe.json").read_text())
            report["probe"] = data
            if any(sha256(Path(path)) != digest for path, digest in assets.items()):
                raise RuntimeError("Model/audio/manifest changed during probe")
            if source_fingerprint() != before or sha256(Path(__file__)) != tool_hash:
                raise RuntimeError("Source changed during probe")
            integration, quality = evaluate_report(data, code)
            report.update(integration_acceptance=integration, fixture_quality_passed=quality,
                          status="PASS" if integration and quality else "FAIL")
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="FAIL", error=str(exc) or type(exc).__name__)
    finally:
        if process is not None:
            try:
                stop_owned_group(process)
            except Exception as exc:
                report.update(status="FAIL", integration_acceptance=False, cleanup_error=str(exc))
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "integration_acceptance", "model_acceptance", "run_directory")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
