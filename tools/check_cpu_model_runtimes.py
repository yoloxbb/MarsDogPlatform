"""Run module-owned auxiliary CPU model probes with pinned input verification."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess

from runtime_environment import ROOT, clean_environment
from prepare_cpu_models import verify, sha256, safe_path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "out/cpu-model-runtimes")
    args = parser.parse_args()
    directory = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    lock_path = ROOT / "config/models/cpu-assets.lock.json"
    lock = json.loads(lock_path.read_text())
    report = {"status": "FAIL", "scope": "Auxiliary CPU runtime smoke, not complete perception/robot acceptance",
              "lock_sha256": sha256(lock_path), "modules": {}}
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Model probes interrupted")
    old = signal.signal(signal.SIGTERM, interrupted)
    try:
        for entry in lock["archive_files"]:
            verify(safe_path(args.assets / "archive", entry["member"]), entry)
        for module in ("vision", "voice"):
            env = clean_environment()
            env.update(PYTHONPATH=str(ROOT / "modules" / module), PYTHONDONTWRITEBYTECODE="1",
                       CUDA_VISIBLE_DEVICES="", YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true",
                       YOLO_CONFIG_DIR=str(directory / "settings"), OMP_NUM_THREADS="2")
            output = directory / (module + ".json")
            cmd = [str(ROOT / "modules" / module / ".venv/bin/python"), "-B",
                   str(ROOT / "modules" / module / "tools/check_cpu_aux_models.py"),
                   "--assets", str(args.assets.resolve()), "--output", str(output)]
            with (directory / (module + ".log")).open("w") as log:
                proc = subprocess.Popen(cmd, env=env, cwd=directory, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = proc.wait(timeout=300)
                except BaseException:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    raise
            if not output.is_file():
                raise RuntimeError(module + " did not produce evidence; exit " + str(code))
            data = json.loads(output.read_text())
            report["modules"][module] = data
            if code or data["status"] != "PASS":
                raise RuntimeError(module + " CPU runtime probe failed")
        for entry in lock["archive_files"]:
            verify(safe_path(args.assets / "archive", entry["member"]), entry)
        report["status"] = "PASS"
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = str(exc) or type(exc).__name__
    finally:
        signal.signal(signal.SIGTERM, old)
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(directory / "result.json")}))
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
