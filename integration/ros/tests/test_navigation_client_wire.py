"""Real Action adapter -> waypoint service -> fake Nav2; isolated ROS domain only."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "navigation_wire_fixture",
    ROOT / "robotics/ros2/src/waypoint_nav/tests/test_wire_integration.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def test_actual_action_client_navigation_and_cancel():
    # Fail, do not skip, if the explicitly requested ROS environment is missing.
    assert fixture.rclpy is not None, "Load Humble, VoiceTask and Nav2 interfaces"
    from marsdog_action_executor.adapters.waypoint_nav_adapter import Ros2WaypointNavClient
    case = fixture.WireIntegrationTests()
    case.setUp()
    try:
        client = Ros2WaypointNavClient(case.client_node)
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(client, "action:integration:cancel", "C", 10.0)
            assert case.goal_started.wait(5), "Nav2 never received navigation goal"
            client.cancel_navigation()
            assert result.result(timeout=15) is False
        assert client.last_outcome.state == "INTERRUPTED"
        assert client.last_outcome.code == "CLIENT_CANCELLED"
        assert not client.navigation_interlocked
        assert case.goal_count == 1
    finally:
        case.tearDown()
