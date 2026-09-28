"""Real subprocess checks for supervisor interruption, crash and duplicate ownership."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "out/local"


def main():
    out = ROOT / "out/local-lifecycle"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for case in ("interrupt", "child_crash"):
        before = set((LOCAL / "runs").iterdir())
        with (out / (case + ".log")).open("w") as log:
            proc = subprocess.Popen([sys.executable, "-B", str(ROOT / "tools/marsdog.py"), "up"],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                record = None
                while time.monotonic() < deadline:
                    assert proc.poll() is None, "Supervisor failed before ready"
                    for directory in set((LOCAL / "runs").iterdir()) - before:
                        candidate = directory / "processes.json"
                        if candidate.is_file():
                            try:
                                entries = json.loads(candidate.read_text())
                            except json.JSONDecodeError:
                                continue
                            if len(entries) == 10:
                                record = candidate
                                break
                    if record:
                        break
                    time.sleep(0.1)
                assert record, "No complete process inventory"
                entries = json.loads(record.read_text())
                time.sleep(1)
                if case == "interrupt":
                    duplicate = subprocess.run([sys.executable, "-B", str(ROOT / "tools/marsdog.py"),
                                                "up", "--duration", "1"], cwd=ROOT,
                                               text=True, capture_output=True, timeout=20)
                    assert duplicate.returncode != 0 and "already running" in duplicate.stderr
                    proc.send_signal(signal.SIGTERM)
                else:
                    action = next(e for e in entries if e["name"] == "action")
                    os.kill(action["pid"], signal.SIGKILL)
                code = proc.wait(timeout=25)
                report = json.loads((record.parent / "result.json").read_text())
                assert report["status"] == ("PASS" if case == "interrupt" else "FAIL"), report
                assert (code == 0) == (case == "interrupt")
                assert not report["forced_shutdowns"]
                if case == "child_crash":
                    assert "action exited unexpectedly" in report["error"]
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
    report = {"status": "PASS", "cases": results, "scope": "Local profile only; no hardware"}
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
