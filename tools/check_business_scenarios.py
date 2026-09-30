"""Installed perception/BT recovery scenarios on a locked localhost ROS domain."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import sys

from runtime_environment import ROOT, ros_environment
from check_voice_cpu_ros import stop_owned_group

CASE_IDS = (
    "voice-held-continuous-session",
    "voice-stop-stale-requests",
    "voice-lease-expiry",
    "voice-restart-rediscovery",
    "vision-timeout-stale-cache",
    "vision-resume-late-response",
    "vision-restart-new-epoch",
)


def evaluate_report(data, returncode):
    """A partial run, stale PASS, or leaked/forced process must fail."""
    if not isinstance(data, dict):
        return False
    cases = data.get("cases", [])
    children = data.get("processes", [])
    provenance = data.get("provenance", {})
    if (not isinstance(cases, list) or not all(isinstance(c, dict) for c in cases)
            or not isinstance(children, list) or not all(isinstance(c, dict) for c in children)
            or not isinstance(provenance, dict)
            or not all(isinstance(p, dict) for p in provenance.values())):
        return False
    if not all(type(c.get("pid")) is int and c["pid"] > 0 for c in children):
        return False
    return bool(
        returncode == 0 and data.get("status") == "PASS"
        and [case.get("id") for case in cases] == list(CASE_IDS)
        and all(case.get("status") == "PASS" for case in cases)
        and data.get("domain") == 216
        and data.get("no_hardware_publishers") is True
        and data.get("real_bt_adapter") is True
        and len(children) == 4
        and {c.get("name") for c in children} == {"voice-1", "voice-2", "vision-1", "vision-2"}
        and len({child.get("pid") for child in children}) == 4
        and all(child.get("returncode") == 0 and child.get("reaped") is True
                and child.get("forced") is False for child in children)
        and all(data.get("provenance", {}).get(name, {}).get("installed") is True
                for name in ("behavior", "voice-1", "voice-2", "vision-1", "vision-2"))
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "out/business-scenarios")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    directory = output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir()
    report = {"status": "RUNNING", "run_directory": str(directory)}
    (output / "result.json").write_text(json.dumps(report) + "\n")
    process = None
    lock_path = ROOT / "out/business-scenarios/domain216.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    def interrupt(signum, frame):
        raise KeyboardInterrupt("Business scenarios interrupted")
    handlers = {s: signal.signal(s, interrupt) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from marsdog import INSTALL, LOCAL, source_fingerprint
            fingerprint = source_fingerprint()
            receipt = json.loads((LOCAL / "build-receipt.json").read_text())
            if receipt["source_sha256"] != fingerprint:
                raise RuntimeError("Install is stale; run tools/marsdog.py build")
            env = ros_environment(INSTALL, domain=216)
            env.update(MARSDOG_LOCAL_SIMULATION="1", ROS_LOG_DIR=str(directory / "ros-log"),
                       MARSDOG_VISION_PROJECT_DIR=str(INSTALL / "marsdog_vision_interaction/share/marsdog_vision_interaction"),
                       MARSDOG_VISION_MODEL_DIR=str(directory / "absent-models"),
                       MARSDOG_VISION_DATA_DIR=str(directory / "vision-data"))
            command = [str(ROOT / "modules/behavior/.venv/bin/python"), "-B",
                       str(ROOT / "integration/scenarios/perception_recovery_probe.py"),
                       "--output", str(directory), "--install", str(INSTALL)]
            with (directory / "probe.log").open("w") as log:
                process = subprocess.Popen(command, cwd=directory, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=120)
                finally:
                    # Children inherit this process group, including a deliberately
                    # stopped Vision. Clean it even when the observer exits first.
                    stop_owned_group(process)
            observation = json.loads((directory / "observation.json").read_text())
            report = {**observation, "status": "PASS" if evaluate_report(observation, code) else "FAIL",
                      "run_directory": str(directory), "source_sha256": fingerprint,
                      "probe_returncode": code, "command": command,
                      "scope": "Installed Voice/Vision mock nodes and real BT perception adapter; ROS DDS and services; no hardware/models/full BT arbitration"}
            if source_fingerprint() != fingerprint:
                raise RuntimeError("Source changed during scenario verification")
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="FAIL", error=str(error))
    finally:
        if process is not None:
            stop_owned_group(process)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(directory / "result.json"),
                      "cases": len(report.get("cases", [])), "error": report.get("error")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
