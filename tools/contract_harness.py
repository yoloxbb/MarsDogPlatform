"""Shared test orchestration only: independent environments and frozen observations."""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from runtime_environment import ROOT, clean_environment, ros_environment


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def run_stage(stage, request, output, worker, *, ros=False):
    source = ROOT / "modules" / stage
    command = [str(source / ".venv/bin/python"), "-B", "-c",
               "import sys,runpy;sys.path.insert(1," + repr(str(worker.parent)) + ");"
               "runpy.run_path(" + repr(str(worker)) + ",run_name='__main__')",
               "--stage", stage]
    env = ros_environment(domain=212) if ros else clean_environment()
    env["TZ"] = "UTC"
    for key in list(env):
        if key.startswith("MARSDOG_"):
            env.pop(key)
    result = subprocess.run(command, cwd=source, env=env,
                            input=json.dumps(request, ensure_ascii=False),
                            capture_output=True, text=True, timeout=120)
    (output / (stage + ".log")).write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(stage + " failed: " + str(output / (stage + ".log")))
    response = json.loads(result.stdout)
    origin = response["provenance"]
    module_file = Path(origin["module_file"])
    if (origin["stage"] != stage or Path(origin["prefix"]) != source / ".venv"
            or not module_file.is_relative_to(source)
            or module_file.is_relative_to(source / ".venv")
            or origin["foreign_business_modules"] or origin["ros_importable"] != ros):
        raise RuntimeError("Invalid module provenance: " + repr(origin))
    return response


def check_main(fixtures, observer, default_output, *, count_stage="behavior"):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=default_output)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "scope": "real module compatibility; pure test transport, no hardware"}
    write_json(output / "result.json", report)
    try:
        baseline_path = fixtures / "baseline.json"
        baseline = json.loads(baseline_path.read_text())
        if (not isinstance(baseline.get("observed"), dict)
                or not baseline["observed"]
                or any(not isinstance(value, dict) or not value
                       for value in baseline["observed"].values())):
            raise ValueError("Baseline must contain nonempty observations for every stage")
        observed, provenance = observer(output)
        write_json(output / "actual.json", observed)
        report.update(baseline_commit=baseline["baseline_commit"],
                      baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                      provenance=provenance, scenarios=len(observed[count_stage]),
                      stage_observations={stage: len(values) for stage, values in observed.items()},
                      skipped=0)
        if observed != baseline["observed"]:
            difference = "\n".join(difflib.unified_diff(
                json.dumps(baseline["observed"], ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                json.dumps(observed, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                fromfile="baseline", tofile="observed", lineterm="",
            ))
            (output / "difference.diff").write_text(difference + "\n")
            raise RuntimeError("Compatibility mismatch: " + str(output / "difference.diff"))
        report["status"] = "PASS"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report.update(status="FAIL", error=str(error))
    write_json(output / "result.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1
