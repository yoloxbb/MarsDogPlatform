"""Real subprocess checks for supervisor interruption, crash and duplicate ownership."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("lite3-local-cpu", "lite3-nav2-cpu"), default="lite3-local-cpu")
    args = parser.parse_args()
    local = ROOT / ("out/nav2-local" if args.profile == "lite3-nav2-cpu" else "out/local")
    expected_count = 16 if args.profile == "lite3-nav2-cpu" else 11
    command = [sys.executable, "-B", str(ROOT / "tools/marsdog.py"), "up", "--profile", args.profile]
    out = ROOT / ("out/nav2-lifecycle" if args.profile == "lite3-nav2-cpu" else "out/local-lifecycle")
    out.mkdir(parents=True, exist_ok=True)
    (local / "runs").mkdir(parents=True, exist_ok=True)
    results = []
    for case in ("interrupt", "child_crash", "collector_crash"):
        before = set((local / "runs").iterdir())
        with (out / (case + ".log")).open("w") as log:
            proc = subprocess.Popen(command,
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                record = None
                while time.monotonic() < deadline:
                    assert proc.poll() is None, "Supervisor failed before ready"
                    for directory in set((local / "runs").iterdir()) - before:
                        candidate = directory / "processes.json"
                        if candidate.is_file():
                            try:
                                entries = json.loads(candidate.read_text())
                            except json.JSONDecodeError:
                                continue
                            if len(entries) == expected_count:
                                record = candidate
                                break
                    if record:
                        break
                    time.sleep(0.1)
                assert record, "No complete process inventory"
                entries = json.loads(record.read_text())
                time.sleep(1)
                if case == "interrupt":
                    duplicate = subprocess.run(command + ["--duration", "1"], cwd=ROOT,
                                               text=True, capture_output=True, timeout=20)
                    assert duplicate.returncode != 0 and "already running" in duplicate.stderr
                    proc.send_signal(signal.SIGTERM)
                elif case == "collector_crash":
                    collector = next(e for e in entries if e["name"] == "logs")
                    os.kill(collector["pid"], signal.SIGKILL)
                    time.sleep(1)
                    assert proc.poll() is None, "Collector failure stopped the business supervisor"
                    for entry in entries:
                        if entry["name"] != "logs":
                            os.kill(entry["pid"], 0)
                    proc.send_signal(signal.SIGTERM)
                else:
                    action = next(e for e in entries if e["name"] == "action")
                    os.kill(action["pid"], signal.SIGKILL)
                code = proc.wait(timeout=40)
                report = json.loads((record.parent / "result.json").read_text())
                assert report["status"] == ("FAIL" if case == "child_crash" else "PASS"), report
                assert (code == 0) == (case != "child_crash")
                assert not report["forced_shutdowns"]
                if case == "child_crash":
                    assert "action exited unexpectedly" in report["error"]
                if case == "collector_crash":
                    assert "collector exited" in report["logging_degraded"]
                for entry in report["processes"]:
                    try:
                        os.kill(entry["pid"], 0)
                    except ProcessLookupError:
                        continue
                    raise AssertionError("Leftover process: " + str(entry))
                results.append({"case": case, "status": "PASS", "run": str(record.parent),
                                "observed_supervisor_status": report["status"], "returncode": code,
                                "all_owned_pids_reaped": True})
            finally:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
    report = {"status": "PASS", "cases": results, "profile": args.profile, "scope": "Local profile only; no hardware"}
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
