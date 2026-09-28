"""Regression across independent processes, invoking the unchanged real implementations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import pytest

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MARSDOG_MIGRATION_WORKSPACE", CODE_ROOT)).resolve()
RUN_ID = os.environ.get("MARSDOG_P1_RUN_ID", "p1-20260928")
SOURCES = ROOT / "work" / RUN_ID / "sources"
DOCUMENT = json.loads((CODE_ROOT / "fixtures/behavior-result/cases.json").read_text())


def stage(name: str, payload: dict) -> dict:
    override = os.environ.get("MARSDOG_" + name.upper() + "_SOURCE")
    source = Path(override) if override else SOURCES / name
    python = source / ".venv/bin/python"
    if not python.exists():
        pytest.fail(f"Required isolated environment missing: {python}")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")):
            env.pop(key)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([
        str(python), "-B", "-c",
        "import runpy; runpy.run_path(" + repr(str(CODE_ROOT / "tools/result_stage.py")) +
        ", run_name='__main__')",
        "--stage", name,
    ], cwd=source, env=env, input=json.dumps(payload), text=True,
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["provenance"]["foreign_business_modules"] == []
    assert Path(response["provenance"]["module_file"]).is_relative_to(source)
    return response


@pytest.mark.parametrize("case", DOCUMENT["cases"], ids=lambda c: c["id"])
def test_action_to_behavior_to_needs(case: dict) -> None:
    action = stage("action", case)
    assert json.loads(action["metadata_json"]) == case["metadata"]
    behavior = stage("behavior", action)
    event = behavior["event"]
    initial = {**DOCUMENT["initial"], **case.get("initial", {})}
    if case["result_type"] is None:
        assert event is None
        events = []
    else:
        assert event["result_type"] == case["result_type"]
        for key, value in case.get("event_metadata", {}).items():
            assert event["metadata"][key] == value
        for key in case.get("absent_metadata", []):
            assert key not in event["metadata"]
        events = [event] * case.get("repeat", 1)
    emotion = stage("emotion", {"initial": initial, "events": events})
    assert emotion["before"] == initial
    assert emotion["after"] == {**initial, **case["after"]}
    assert emotion["accepted"] == case["accepted"]
    assert len({r["provenance"]["pid"] for r in (action, behavior, emotion)}) == 3
