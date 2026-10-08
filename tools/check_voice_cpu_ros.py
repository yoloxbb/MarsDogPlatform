"""Isolated installed Voice CPU pipeline gate; no hardware or default profile changes."""
import argparse
from model_assets import default_manifest
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


def evaluate_report(data, code, *, with_behavior=False):
    integration = (code == 0 and data.get("integration_acceptance") is True
                   and data.get("worker_returncode") == 0
                   and data.get("real_asr_cases") == 1 and data.get("text_fixture_cases") == (7 if with_behavior else 6)
                   and data.get("after_stop_no_inference") is True
                   and data.get("in_flight", {}).get("status") == "PASS"
                   and data["in_flight"].get("late_semantic_events") == 0
                   and data["in_flight"].get("recovery_catalog_dispatch") is True
                   and isinstance(data.get("worker", {}).get("pid"), int)
                   and isinstance(data.get("observer_pid"), int)
                   and data["worker"]["pid"] > 0 and data["observer_pid"] > 0
                   and data["worker"]["pid"] != data["observer_pid"])
    expected = ["upstream-zh-itn", "qwen-sit", "qwen-no-sit", "qwen-reject", "catalog-sit"]
    integration = integration and [x.get("id") for x in data.get("cases", [])] == expected
    integration = integration and all(not x["transport_errors"] for x in data.get("cases", []))
    if with_behavior:
        chain = data.get("behavior_chain", {})
        integration = (integration and chain.get("status") == "PASS"
                       and bool(chain.get("navigation_goal_id"))
                       and chain.get("navigation_success") is True
                       and chain.get("no_hardware_publishers") is True)
    quality = bool(integration and all(not x["quality_errors"] for x in data["cases"]))
    return bool(integration), quality


def acceptance_status(integration, quality, mode):
    if mode not in {"strict", "flow"}:
        raise ValueError("Unknown acceptance mode")
    return "PASS" if integration and (quality or mode == "flow") else "FAIL"


def main(argv=None, *, trial=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-manifest", type=Path,
                        default=None)
    parser.add_argument("--intent-manifest", type=Path,
                        default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "out/voice-cpu-ros")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--acceptance", choices=("strict", "flow"), default="strict")
    parser.add_argument("--with-behavior", action="store_true",
                        help="Include installed BT/Action/Needs and simulated Lite3/navigation")
    args = parser.parse_args(argv)
    args.voice_manifest = args.voice_manifest or default_manifest("voice")
    args.intent_manifest = args.intent_manifest or default_manifest("intent")
    if not 30 <= args.timeout <= 600:
        parser.error("timeout must be 30..600 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    directory = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir()
    report = {"status": "FAIL", "integration_acceptance": False, "model_acceptance": False,
              "run_directory": str(directory), "domain": 215, "acceptance": args.acceptance, "with_behavior": args.with_behavior}
    lock_path = ROOT / "out/voice-cpu-ros/domain215.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    process = None
    components, component_logs = [], []
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
            request_data = json.loads(request.read_text())
            request_data["with_behavior"] = args.with_behavior
            if trial is not None:
                if not args.with_behavior:
                    raise ValueError("Recording trials require the behavior chain")
                request_data["trial"] = trial
                assets[trial["wav"]] = sha256(Path(trial["wav"]))
            request.write_text(json.dumps(request_data, ensure_ascii=False, indent=2) + "\n")
            tool_hash = sha256(Path(__file__))
            report.update(assets_sha256=assets, source_fingerprint=before, tool_sha256=tool_hash)
            env = ros_environment(INSTALL, 215)
            from log_runs import prepare_logging
            prepare_logging(env, directory)
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                       ROS_LOG_DIR=str(directory / "ros-log"))
            if args.with_behavior:
                from marsdog import BUILD_TOOLS, process_specs
                env.update(MARSDOG_LOCAL_SIMULATION="1",
                           MARSDOG_VISION_PROJECT_DIR=str(INSTALL / "marsdog_vision_interaction/share/marsdog_vision_interaction"),
                           MARSDOG_VISION_MODEL_DIR=str(directory / "absent-models"),
                           MARSDOG_VISION_DATA_DIR=str(directory / "vision-data"))
                subprocess.run([str(BUILD_TOOLS / "python"), "-B", str(ROOT / "tools/prepare_local_configs.py"),
                                "--run", str(directory), "--install", str(INSTALL)],
                               env=env, check=True, capture_output=True, timeout=30)
                prefix = request_data["prefix"]
                for name, cmd in process_specs(directory):
                    if name == "voice":
                        continue  # Only the real installed CPU Voice worker may publish.
                    cmd = list(cmd)
                    if "--ros-args" not in cmd:
                        cmd.append("--ros-args")
                    for endpoint in ("/perception/audio_event", "/perception/voice/task"):
                        cmd += ["-r", endpoint + ":=" + prefix + endpoint]
                    stream = (directory / (name + ".log")).open("w")
                    component_logs.append(stream)
                    child_env = dict(env, MARSDOG_PYTHON=cmd[0])
                    child = subprocess.Popen(cmd, cwd=directory, env=child_env, stdout=stream,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    components.append((name, child, cmd))
            python = ROOT / "modules/voice/.venv/bin/python"
            env["MARSDOG_PYTHON"] = str(python)
            probe_script = "recording_trial_probe.py" if trial is not None else "ros_cpu_pipeline_probe.py"
            command = [str(python), "-B", str(ROOT / "modules/voice/tests" / probe_script),
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
            if any(child.poll() is not None for name, child, _ in components if name != "logs"):
                raise RuntimeError("A behavior-chain component exited before validation completed")
            if trial is None:
                integration, quality = evaluate_report(data, code, with_behavior=args.with_behavior)
            else:
                from trial_report import evaluate_trial
                integration, quality = evaluate_trial(data, code)
            report.update(integration_acceptance=integration, fixture_quality_passed=quality,
                          status=acceptance_status(integration, quality, args.acceptance))
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="FAIL", error=str(exc) or type(exc).__name__)
    finally:
        if process is not None:
            try:
                stop_owned_group(process)
            except Exception as exc:
                report.update(status="FAIL", integration_acceptance=False, cleanup_error=str(exc))
        report["components"] = []
        for name, child, cmd in reversed(components):
            try:
                stop_owned_group(child)
            except Exception as exc:
                report.update(status="FAIL", integration_acceptance=False, cleanup_error=str(exc))
            report["components"].append({"name": name, "pid": child.pid, "command": cmd,
                                         "shutdown_returncode": child.returncode})
            if name == "logs" and child.returncode != 0:
                report["logging_degraded"] = "collector exited: " + str(child.returncode)
            elif child.returncode != 0:
                report.update(status="FAIL", integration_acceptance=False,
                              component_shutdown_error=f"{name}: {child.returncode}")
        for stream in component_logs:
            stream.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if trial is not None:
            from trial_report import write_trial_report
            report["trial"] = trial
            try:
                write_trial_report(directory, report)
            except Exception as exc:
                report.update(status="FAIL", diagnostics_error=str(exc))
        from log_runs import finish_logging
        finish_logging(directory, report["status"])
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "integration_acceptance", "model_acceptance", "run_directory")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
