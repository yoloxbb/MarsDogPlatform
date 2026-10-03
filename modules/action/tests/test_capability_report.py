"""Configuration reports must keep backend gates and hardware evidence distinct."""
from pathlib import Path
import pytest
from marsdog_action_executor.capability_report import report
from marsdog_action_executor.adapters.lite3_backend import Lite3ChassisBackend

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_defaults_preserve_disabled_backend_and_unknown_hardware():
    result = report(CONFIG)
    assert result["units"]["ACT_BASIC_SIT"]["configuration_status"] == "blocked"
    assert result["units"]["ACT_BASIC_SIT"]["reason"] == "lite3_backend_disabled"
    assert all(v["hardware_acceptance"] == "unknown" for v in result["units"].values())
    assert all(v["hardware_acceptance"] == "unknown" for v in result["behaviors"].values())


def test_runtime_override_does_not_bypass_original_policy_or_mutate_config():
    before = {p: p.read_bytes() for p in CONFIG.glob("*.yaml")}
    result = report(CONFIG, runtime={"lite3_enabled": True, "lite3_allow_proxies": True, "lite3_allow_unverified": False})
    sit = result["units"]["ACT_BASIC_SIT"]
    assert sit["reason"] == "lite3_policy_gated" and sit["policy_allowed"] is False
    assert result["behaviors"]["sit_down"]["configuration_status"] == "blocked"
    assert {p: p.read_bytes() for p in before} == before


def test_report_uses_backend_policy_and_never_publishes(monkeypatch):
    seen = []
    original = Lite3ChassisBackend.can_execute
    def inspect(self, unit_id):
        seen.append(unit_id)
        return original(self, unit_id)
    monkeypatch.setattr(Lite3ChassisBackend, "can_execute", inspect)
    result = report(CONFIG, runtime={"lite3_enabled": True})
    expected = {name for name, item in result["units"].items() if item["route"] == "lite3"}
    assert set(seen) == expected
    assert expected


@pytest.mark.parametrize("runtime", [{"lite3_allow_unverified": "false"}, {"unknown_flag": True}])
def test_invalid_override_cannot_turn_into_truthy_authorization(runtime):
    with pytest.raises(ValueError):
        report(CONFIG, runtime=runtime)
