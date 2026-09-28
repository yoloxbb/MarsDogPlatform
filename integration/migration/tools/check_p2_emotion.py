"""Build the migrated Emotion and compare installed ROS behavior to the P1 baseline."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import subprocess

from baseline_lib import ROOT, WORKSPACE, verify_sources
from check_ros import ros_env, run_build


def main() -> None:
    assert verify_sources()["status"] == "PASS", "Original source drift"
    work = ROOT / "work/p1-20260928"
    report = ROOT / "reports/p1-20260928"
    result = {
        "scope": "P2 Emotion software verification, not full robot acceptance",
        "build": run_build(
            WORKSPACE / "marsdog-platform/modules/emotion", "p2-emotion", work,
            report, ros_env(), ROOT / "ros-tools/.venv",
        ),
        "probes": {},
    }
    if result["build"]["status"] == "PASS":
        prefixes = {
            "baseline": work / "ros-emotion-humble59/install",
            "migrated": Path(result["build"]["install"]),
        }
        for name, prefix in prefixes.items():
            env = ros_env([prefix])
            env.update(
                ROS_DOMAIN_ID=str(180 + secrets.randbelow(30)), ROS_LOCALHOST_ONLY="1",
                RMW_IMPLEMENTATION="rmw_fastrtps_cpp", ROS_LOG_DIR=str(report / "p2-ros-logs"),
            )
            output = report / f"p2-emotion-{name}-ros-probe.json"
            args = [
                str(ROOT / "ros-tools/.venv/bin/python"), "-B",
                str(ROOT / "tools/ros_emotion_probe.py"), "--install", str(prefix),
                "--output", str(output),
            ]
            with (report / f"p2-emotion-{name}-ros-probe.log").open("w") as stream:
                completed = subprocess.run(args, cwd=work, env=env, stdout=stream,
                                           stderr=subprocess.STDOUT, timeout=45)
            result["probes"][name] = {
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "exit_code": completed.returncode, "command": args,
                "ros_domain_id": env["ROS_DOMAIN_ID"], "localhost_only": True,
                "result": json.loads(output.read_text()) if completed.returncode == 0 else None,
            }
        executables = sorted(path.name for path in (
            prefixes["migrated"] / "marsdog_need_emotion/lib/marsdog_need_emotion"
        ).iterdir() if path.is_file())
        expected = sorted([
            "time_controller_node", "midnight_test_node", "internal_need_node",
            "emotion_engine_node", "personality_node", "one1000_tactile_node",
        ])
        result["executables"] = {
            "status": "PASS" if executables == expected else "FAIL", "actual": executables,
        }
    result["original_sources"] = verify_sources()
    checks = [result["build"], result["original_sources"], *result["probes"].values()]
    checks.append(result.get("executables", {"status": "BLOCKED"}))
    result["status"] = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    (report / "p2-emotion-ros.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
