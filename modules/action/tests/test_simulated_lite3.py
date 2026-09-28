"""Local simulation is opt-in and retains the real backend navigation lifecycle."""
import pytest
from marsdog_action_executor.adapters.simulated_lite3 import (
    SimulatedLite3IO, require_local_simulation,
)
from marsdog_action_executor.adapters.lite3_backend import (
    Lite3ChassisBackend, Lite3SimpleCommand, CMD_STAND_LIE_TOGGLE, STATE_LIE, STATE_STAND,
)

def test_simulation_requires_all_profile_guards(monkeypatch):
    for key in ("MARSDOG_LOCAL_SIMULATION", "ROS_LOCALHOST_ONLY", "ROS_DOMAIN_ID"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError):
        require_local_simulation()
    monkeypatch.setenv("MARSDOG_LOCAL_SIMULATION", "1")
    monkeypatch.setenv("ROS_LOCALHOST_ONLY", "1")
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    with pytest.raises(RuntimeError):
        require_local_simulation()
    monkeypatch.setenv("ROS_DOMAIN_ID", "210")
    require_local_simulation()

def test_simulated_io_reports_explicit_synthetic_commands_and_posture():
    events = []
    io = SimulatedLite3IO(events.append)
    io.command(Lite3SimpleCommand(CMD_STAND_LIE_TOGGLE))
    assert io.posture == STATE_LIE
    io.command(Lite3SimpleCommand(CMD_STAND_LIE_TOGGLE))
    assert io.posture == STATE_STAND
    assert len(events) == 2 and all(e["simulated"] is True for e in events)
    assert all("battery_observation" not in e for e in events)

def test_navigation_uses_real_backend_with_synthetic_io_only():
    events = []
    io = SimulatedLite3IO(events.append)
    backend = Lite3ChassisBackend(io.command, io.twist, {},
        mode_settle_sec=0, navigation_stable_samples=2,
        sleep=lambda _seconds: io.status_tick())
    io.backend = backend
    io.status_tick()
    assert backend.prepare_navigation(), backend.last_error
    assert backend.finish_navigation(), backend.last_error
    assert any(e["kind"] == "simple_command" for e in events)
    assert any(e["kind"] == "twist" for e in events)
    assert all(e["simulated"] for e in events)
