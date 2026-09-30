"""Compare real Voice -> BT/Emotion behavior against the pre-refactor oracle."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from runtime_environment import ROOT, clean_environment

FIXTURES = ROOT / "interfaces/application/audio-event-v2"
WORKER = ROOT / "integration/contracts/audio_stage.py"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def run_stage(stage, request, output):
    source = ROOT / "modules" / stage
    python = source / ".venv/bin/python"
    command = [str(python), "-B", "-c",
               "import runpy; runpy.run_path(" + repr(str(WORKER)) + ", run_name='__main__')",
               "--stage", stage]
    env = clean_environment()
    # Developer overrides must not redirect the test to a different config.
    for key in list(env):
        if key.startswith("MARSDOG_"):
            env.pop(key)
    result = subprocess.run(
        command, cwd=source, env=env, input=json.dumps(request, ensure_ascii=False),
        capture_output=True, text=True, timeout=120,
    )
    (output / (stage + ".log")).write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(stage + " worker failed; see " + str(output / (stage + ".log")))
    response = json.loads(result.stdout)
    provenance = response["provenance"]
    if (provenance["stage"] != stage
            or Path(provenance["prefix"]).absolute() != source / ".venv"
            or not Path(provenance["module_file"]).is_relative_to(source)
            or Path(provenance["module_file"]).is_relative_to(source / ".venv")
            or provenance["foreign_business_modules"] or provenance["ros_importable"]):
        raise RuntimeError("Invalid module provenance: " + repr(provenance))
    return response


def expand_scenarios(fixtures, produced):
    scenarios = []
    for scenario in fixtures["scenarios"]:
        wires = []
        for step in scenario["steps"]:
            if "raw" in step:
                wire = step["raw"]
            else:
                payload = dict(produced[step["source"]][step.get("index", 0)])
                payload.update(step.get("patch", {}))
                for key in step.get("remove", []):
                    payload.pop(key, None)
                wire = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            wires.append(wire)
        scenarios.append({"id": scenario["id"], "wires": wires})
    return scenarios


def observe(output):
    fixtures = json.loads((FIXTURES / "cases.json").read_text())
    voice = run_stage("voice", fixtures["producers"], output)
    scenarios = expand_scenarios(fixtures, voice["observed"])
    responses = {
        "voice": voice,
        "behavior": run_stage("behavior", scenarios, output),
        "emotion": run_stage("emotion", scenarios, output),
    }
    provenance = {stage: response["provenance"] for stage, response in responses.items()}
    if len({value["pid"] for value in provenance.values()}) != len(responses):
        raise RuntimeError("Stages must run in separate processes")
    # Preserve exact input bytes for diagnosis; both consumers receive this list.
    write_json(output / "wires.json", scenarios)
    return {stage: response["observed"] for stage, response in responses.items()}, provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "out/audio-contracts")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "scope": "pure real-module compatibility; no DDS/models/hardware"}
    write_json(output / "result.json", report)
    try:
        expected_path = FIXTURES / "baseline.json"
        expected = json.loads(expected_path.read_text())
        actual, provenance = observe(output)
        write_json(output / "actual.json", actual)
        report.update(provenance=provenance, baseline_commit=expected["baseline_commit"],
                      baseline_sha256=hashlib.sha256(expected_path.read_bytes()).hexdigest(),
                      scenarios=len(actual["behavior"]), skipped=0)
        if actual != expected["observed"]:
            difference = "\n".join(difflib.unified_diff(
                json.dumps(expected["observed"], ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
                fromfile="frozen baseline", tofile="actual", lineterm="",
            ))
            (output / "difference.diff").write_text(difference + "\n")
            raise RuntimeError("Compatibility mismatch; see " + str(output / "difference.diff"))
        report["status"] = "PASS"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        report.update(status="FAIL", error=str(error))
    write_json(output / "result.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
