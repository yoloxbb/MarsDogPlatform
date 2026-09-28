"""BT transport adapter -> real Action node -> waypoint dispatcher -> fake Nav2.

Includes tree execution with fixture event selection, not production ROS arbitration. The only hardware replacement is the
SportMode publisher; configuration overrides live in a temporary directory.
"""
import importlib.util
import os
import json
import subprocess
from pathlib import Path
import shutil
import threading
import time

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "chain_fixture", ROOT / "robotics/ros2/src/waypoint_nav/tests/test_wire_integration.py")
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


class RecordingSportPublisher:
    def __init__(self, *_args, **_kwargs):
        self.requests = []
        self.topic = "memory-only"
        self.matched_subscribers = 1

    def __call__(self, request):
        self.requests.append(request)
        return True


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for chain state")


@pytest.mark.parametrize("scenario", [
    "tree_voice", "tree_need", "tree_need_proxy", "complete_behavior", "go_home_arrival", "lost_status", "cancel", "success_cancel_race", "dispatcher_restart",
])
def test_behavior_navigation_chain(monkeypatch, tmp_path, scenario):
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    assert os.environ.get("ROS_DOMAIN_ID") == "89"
    assert wire.rclpy is not None
    from marsdog_action_executor import ros_node
    from marsdog_behavior.action_client_adapter import ActionClientAdapter
    from bionic_dog_bt.datatypes import ActiveBehavior
    from bionic_dog_bt.constants import GOAL_TERMINAL, GOAL_CANCEL_REQUESTED

    config = tmp_path / "config"
    shutil.copytree(ROOT / "modules/action/config", config)
    for filename, edits in {
        "go2_sport.yaml": {"enabled": True},
        "uwb_follow.yaml": {"enabled": False},
        "wake_orientation.yaml": {"enabled": False},
        "visual_target_approach.yaml": {"enabled": False},
    }.items():
        path = config / filename
        data = yaml.safe_load(path.read_text())
        data.update(edits)
        path.write_text(yaml.safe_dump(data))
    path = config / "sound_config.yaml"
    data = yaml.safe_load(path.read_text())
    data["bark_sound"]["enabled"] = False
    path.write_text(yaml.safe_dump(data))
    path = config / "navigation_waypoints.yaml"
    data = yaml.safe_load(path.read_text())
    data["enabled"] = True
    data["random_navigation_fixed_pool"] = ["A"]
    data["waypoint_nav"]["places"]["A"] = "A"
    data["waypoint_nav"]["places"]["B"] = "A"
    data["waypoint_nav"]["cancel_confirmation_timeout_sec"] = 0.3
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(ros_node.ActionExecutorNode, "_resolve_config_dir", staticmethod(lambda: config))
    monkeypatch.setattr(ros_node, "Ros2Go2SportPublisher", RecordingSportPublisher)
    original_init = wire.rclpy.init
    monkeypatch.setattr(wire.rclpy, "init", lambda args: original_init(args=args + [
        "-p", "attention_tracking_enabled:=false", "-p", "target_approach_enabled:=false",
    ]))

    class ChainFixture(wire.WireIntegrationTests):
        def _execute_goal(self, handle):
            self.goal_count += 1
            self.goal_started.set()
            while wire.rclpy.ok():
                if scenario in {"tree_voice", "tree_need", "tree_need_proxy", "complete_behavior", "go_home_arrival", "lost_status"}:
                    handle.succeed()
                    return wire.NavigateToPose.Result()
                if handle.is_cancel_requested:
                    self.cancel_seen.set()
                    self.finish.wait(5)
                    if scenario == "success_cancel_race":
                        handle.succeed()
                    else:
                        handle.canceled()
                    return wire.NavigateToPose.Result()
                time.sleep(0.01)
            handle.abort()
            return wire.NavigateToPose.Result()

    case = ChainFixture()
    case.cancel_seen = threading.Event()
    case.finish = threading.Event()
    case.setUp()
    action = None
    adapter = None
    query_calls = []
    try:
        if scenario == "lost_status":
            # Drop only transport publications; persisted states/query stay real.
            monkeypatch.setattr(case.dispatcher, "_publish_status", lambda _status: None)
            original_query = case.dispatcher._fill_query
            def track_query(response, params):
                query_calls.append(params["target_task_id"])
                return original_query(response, params)
            monkeypatch.setattr(case.dispatcher, "_fill_query", track_query)
        action = ros_node.ActionExecutorNode()
        if scenario in {"tree_need", "tree_need_proxy"}:
            # Deterministically exercise one existing candidate AFTER complete
            # config validation. The real eligibility and execution still run.
            stage = action._config.behavior_tree_templates["recharge"]["stages"][0]
            unit = "ACT_RETURN_TO_CHARGER" if scenario == "tree_need" else "ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER"
            stage["candidates"] = [c for c in stage["candidates"] if c["unit_id"] == unit]
            assert len(stage["candidates"]) == 1
        case.executor.add_node(action)
        adapter = ActionClientAdapter(case.client_node, "/execute_behavior")
        assert adapter._client.wait_for_server(timeout_sec=5)
        behavior = "walk_to_random_point" if scenario == "complete_behavior" else "go_home"
        active = ActiveBehavior("chain-" + scenario, behavior, 1, 1.0, 1.0, "Energy")
        tree = bb = None
        if scenario in {"tree_voice", "tree_need", "tree_need_proxy"}:
            from bionic_dog_bt.tree_builder import create_runtime, build_tree
            _, bb, _, provider, _ = create_runtime(
                config_path=str(ROOT / "modules/behavior/config/behaviors.yaml"))
            event = "EVT_VOICE_COMMAND_GO_HOME" if scenario == "tree_voice" else "NEED_ENERGY_OVERFLOW"
            candidate = provider.inject_event(event)
            assert candidate is not None
            assert candidate.behavior_name == ("go_home" if scenario == "tree_voice" else "recharge")
            # Hardware proxy stage durations are not the subject of this gate.
            candidate.timeout_sec = 30.0
            bb.set_active_behavior(provider.select())
            tree = build_tree(bb, adapter)
            tree.reset()
            tree.tick()
            goal = bb.current_goal_id
            assert goal
        else:
            goal = adapter.send_goal(active)
        assert case.goal_started.wait(5), "Goal did not traverse Action and waypoint service"
        if scenario in {"cancel", "success_cancel_race"}:
            until(lambda: goal in adapter._goal_handles)
            assert adapter.cancel_goal(goal)
            until(lambda: adapter._cancel_futures[goal].done())
            assert adapter.get_goal_lifecycle(goal) == GOAL_CANCEL_REQUESTED
            assert adapter.get_result(goal) is None
            assert case.cancel_seen.wait(5)
            assert adapter.has_goal(goal)
            case.finish.set()
        elif scenario == "dispatcher_restart":
            until(lambda: case.dispatcher._store.active()["code"] == "NAV2_ACCEPTED")
            case._replace_dispatcher()
            assert case.cancel_seen.wait(5), "Restart did not cancel persisted Nav2 UUID"
            assert adapter.get_result(goal) is None
            case.finish.set()
        until(lambda: adapter.get_goal_lifecycle(goal) == GOAL_TERMINAL, timeout=15)
        result = None if tree is not None else adapter.get_result(goal)
        if tree is not None:
            tree.reset()
            tree.tick()
            assert bb.last_feedback_event is not None
            result = bb.last_feedback_event
            from marsdog_behavior import result_event_mapper
            assert Path(result_event_mapper.__file__).resolve().is_relative_to(ROOT / "modules/behavior")
            ResultEventMapper = result_event_mapper.ResultEventMapper
            event = ResultEventMapper().build_result_event(
                result.behavior_name, result.status, result.metadata)
            if scenario == "tree_voice":
                assert result.status == "SUCCESS", result
                assert event is None, "Voice command must not settle Needs"
            else:
                if scenario == "tree_need":
                    assert result.status == "FAILURE", result
                    assert result.reason == "task adapter does not implement execute_task"
                else:
                    assert result.status == "SUCCESS", result
                assert event is not None
                assert "energyValue" not in result.metadata
                assert "charging_completed" not in result.metadata
                assert result.metadata.get("energy_settlement") == ("observation_unavailable" if scenario == "tree_need_proxy" else None)
                payload = json.loads(event)
                assert "energyValue" not in payload["metadata"]
                assert payload["result_type"] == ("FAILED" if scenario == "tree_need" else "COMPLETED")
                env = dict(os.environ)
                for key in list(env):
                    if key.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")) or key in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}:
                        env.pop(key, None)
                worker = ROOT / "integration/migration/tools/result_stage.py"
                response = subprocess.run([
                    str(ROOT / "modules/emotion/.venv/bin/python"), "-B", str(worker), "--stage", "emotion"],
                    cwd=ROOT / "modules/emotion", env=env,
                    input=json.dumps({"initial": {"Energy": 90}, "events": [payload, payload]}),
                    text=True, capture_output=True, timeout=20)
                assert response.returncode == 0, response.stderr
                settled = json.loads(response.stdout)
                assert settled["accepted"] == [False, False]
                assert settled["after"]["Energy"] == 90
                assert settled["provenance"]["foreign_business_modules"] == []
        if scenario in {"tree_voice", "tree_need_proxy", "complete_behavior"}:
            assert result.status == "SUCCESS", result
            assert action._waypoint_nav_client.last_outcome.code == "NAV2_SUCCEEDED"
        elif scenario in {"go_home_arrival", "lost_status"}:
            assert action._waypoint_nav_client.last_outcome.state == "SUCCEEDED"
            assert result.status == "SUCCESS", result
            # Existing hold sends only stop commands, never another motion.
            assert action._go2_publisher.requests
            assert all(request.api_id == 1003 for request in action._go2_publisher.requests)
        elif scenario == "success_cancel_race":
            assert action._waypoint_nav_client.last_outcome.state == "SUCCEEDED"
            assert action._waypoint_nav_client.last_outcome.code == "NAV2_SUCCEEDED"
            assert result.status == "CANCELED", result
        elif scenario == "cancel":
            assert result.status == "CANCELED", result
        else:
            assert result.status != "SUCCESS", result
        if scenario == "lost_status":
            assert query_calls, "Missing publications were not recovered through query"
        assert case.goal_count == 1, "Recovery replayed a navigation goal"
        assert case.dispatcher._store.active() is None
        assert not action._waypoint_nav_client.navigation_interlocked
    finally:
        case.finish.set()
        if adapter:
            adapter._client.destroy()
        if action:
            case.executor.remove_node(action)
            action.destroy_node()
        case.tearDown()
