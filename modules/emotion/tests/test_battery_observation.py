from copy import deepcopy
import pytest
from marsdog_core import MarsdogNeedSystem


def event():
    return {"event_id": "meter-1", "action_type": "ACTION_RECHARGE",
            "result_type": "COMPLETED", "metadata": {"battery_observation": {
                "schema_version": 1, "percentage": 88, "source": "test_meter",
                "observed_at": 999.0, "simulated": False}}}


@pytest.mark.parametrize("status", ["COMPLETED", "INTERRUPTED", "TIMEOUT"])
def test_measured_energy_updates_once_without_proving_charging(status):
    system = MarsdogNeedSystem(timeProvider=lambda: 1000.0)
    system.SetDemandValue("Energy", 90)
    payload = event()
    payload["result_type"] = status
    payload["metadata"]["charging_completed"] = False
    assert system.OnBehaviorResultEvent(payload)
    assert system.GetDemandValue("Energy") == 12
    assert not system.OnBehaviorResultEvent(payload)


@pytest.mark.parametrize("field,value", [
    ("percentage", True), ("percentage", "88"), ("percentage", -1),
    ("percentage", 101), ("percentage", 10 ** 1000), ("percentage", float("nan")), ("percentage", float("inf")),
    ("observed_at", 994), ("observed_at", 1001), ("observed_at", True),
    ("source", ""), ("source", 1), ("simulated", True), ("simulated", 0),
    ("schema_version", True), ("schema_version", 2),
])
def test_invalid_evidence_preserves_energy(field, value):
    system = MarsdogNeedSystem(timeProvider=lambda: 1000.0)
    system.SetDemandValue("Energy", 90)
    payload = event()
    payload["metadata"]["battery_observation"][field] = value
    assert not system.OnBehaviorResultEvent(payload)
    assert system.GetDemandValue("Energy") == 90


def test_rejected_event_id_cannot_be_reused_for_late_measurement():
    system = MarsdogNeedSystem(timeProvider=lambda: 1000.0)
    system.SetDemandValue("Energy", 90)
    payload = event()
    invalid = deepcopy(payload)
    invalid["metadata"] = {"energyValue": 100}
    assert not system.OnBehaviorResultEvent(invalid)
    assert not system.OnBehaviorResultEvent(payload)
    payload["event_id"] = "new-observation"
    assert system.OnBehaviorResultEvent(payload)


def test_conflicting_legacy_scalar_is_rejected():
    system = MarsdogNeedSystem(timeProvider=lambda: 1000.0)
    system.SetDemandValue("Energy", 90)
    payload = event()
    payload["metadata"]["energyValue"] = 100
    assert not system.OnBehaviorResultEvent(payload)
    assert system.GetDemandValue("Energy") == 90


@pytest.mark.parametrize("percentage,stamp", [(0, 1000), (100, 995), (88.9, 999)])
def test_range_freshness_boundaries_and_existing_integer_conversion(percentage, stamp):
    system = MarsdogNeedSystem(timeProvider=lambda: 1000.0)
    system.SetDemandValue("Energy", 90)
    payload = event()
    payload["metadata"]["battery_observation"].update(percentage=percentage, observed_at=stamp)
    assert system.OnBehaviorResultEvent(payload)
    assert system.GetDemandValue("Energy") == 100 - int(percentage)
