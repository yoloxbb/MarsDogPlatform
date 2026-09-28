"""Characterize current energy settlement; read-only business calls in isolated workers."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).with_name("result_stage.py")

def stage(name, data):
    source = ROOT / "modules" / name
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")) or key in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"}:
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    run = subprocess.run([str(source / ".venv/bin/python"), "-B", str(WORKER),
                          "--stage", name], cwd=source, env=env,
                         input=json.dumps(data), text=True, capture_output=True, timeout=30)
    if run.returncode:
        raise RuntimeError(run.stderr)
    result = json.loads(run.stdout)
    assert result["provenance"]["foreign_business_modules"] == []
    return result


def main():
    cases = [
        ("missing", {}),
        ("invalid", {"energyValue": "bad"}),
        ("explicit_incomplete", {"energyValue": 100, "charging_completed": False}),
        ("numeric_88_no_provenance", {"energyValue": 88}),
    ]
    report = {"scope": "Current behavior characterization, not acceptance of energy truth", "cases": []}
    for name, metadata in cases:
        behavior = stage("behavior", {"behavior_name": "recharge", "status": "SUCCESS",
                                      "metadata_json": json.dumps(metadata)})
        event = behavior["event"]
        emotion = stage("emotion", {"initial": {"Energy": 90}, "events": [event, event]})
        report["cases"].append({"name": name, "input_metadata": metadata,
                                "mapped_event": event, "needs": emotion,
                                "behavior_provenance": behavior["provenance"]})
    direct = {"event_id": "energy-audit-direct", "timestamp": 1000,
              "action_type": "ACTION_RECHARGE", "demand_type": "Energy",
              "result_type": "COMPLETED", "metadata": {}}
    report["direct_missing_metadata"] = stage("emotion", {
        "initial": {"Energy": 90}, "events": [direct, direct]})
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
