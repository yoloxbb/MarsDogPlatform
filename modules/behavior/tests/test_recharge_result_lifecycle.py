import json
import time

from bionic_dog_bt.datatypes import BehaviorFeedbackEvent
from marsdog_behavior.intent_mapper import IntentMapper
from marsdog_behavior.result_event_mapper import ResultEventMapper
from marsdog_behavior.runtime import BehaviorRuntime


class _ImmediateRechargeExecutor:
    def __init__(self) -> None:
        self.goal_id = "recharge-goal-1"
        self.active = None
        self.return_result = False
        self.removed = False
        self.canceled_goal_ids = []

    def send_goal(self, active):
        self.active = active
        return self.goal_id

    def cancel_goal(self, goal_id):
        self.canceled_goal_ids.append(goal_id)
        return goal_id == self.goal_id

    def tick(self):
        return None

    def get_feedback(self, goal_id):
        return None

    def get_result(self, goal_id):
        if not self.return_result:
            return None
        return BehaviorFeedbackEvent(
            behavior_id=self.active.behavior_id,
            behavior_name="recharge",
            status="SUCCESS",
            result="completed",
            reason="charging action completed",
            metadata={"energyValue": 88},
        )

    def remove_goal(self, goal_id):
        self.removed = True

    def has_goal(self, goal_id):
        return not self.removed


class _ControlledQueueExecutor:
    def __init__(self) -> None:
        self.goals = {}
        self.completed = set()
        self.canceled_goal_ids = []

    def send_goal(self, active):
        goal_id = f"goal-{len(self.goals) + 1}"
        self.goals[goal_id] = active
        return goal_id

    def cancel_goal(self, goal_id):
        self.canceled_goal_ids.append(goal_id)
        return True

    def tick(self):
        return None

    def get_feedback(self, goal_id):
        return None

    def get_result(self, goal_id):
        if goal_id not in self.completed:
            return None
        self.completed.remove(goal_id)
        active = self.goals[goal_id]
        return BehaviorFeedbackEvent(
            behavior_id=active.behavior_id,
            behavior_name=active.behavior_name,
            status="SUCCESS",
            result="completed",
            reason="controlled completion",
            metadata=(
                {"energyValue": 88}
                if active.behavior_name == "recharge"
                else {}
            ),
        )

    def remove_goal(self, goal_id):
        return None

    def has_goal(self, goal_id):
        return goal_id in self.goals


def test_recharge_success_emits_exact_internal_need_contract() -> None:
    mapper = ResultEventMapper()
    payload = json.loads(
        mapper.build_result_event(
            "recharge", "SUCCESS", {"energyValue": 88}
        )
    )
    assert payload["action_type"] == "ACTION_RECHARGE"
    assert payload["demand_type"] == "Energy"
    assert payload["result_type"] == "COMPLETED"
    assert payload["metadata"]["energyValue"] == 88


def test_recharge_success_without_meter_defaults_to_full_battery() -> None:
    mapper = ResultEventMapper()
    payload = json.loads(mapper.build_result_event("recharge", "SUCCEEDED", {}))
    assert payload["result_type"] == "COMPLETED"
    assert payload["metadata"]["energyValue"] == 100


def test_recharge_energy_alias_is_canonical_and_clamped() -> None:
    mapper = ResultEventMapper()
    payload = json.loads(
        mapper.build_result_event(
            "recharge", "COMPLETED", {"batteryValue": 120}
        )
    )
    assert payload["metadata"]["energyValue"] == 100
    assert "batteryValue" not in payload["metadata"]


def test_terminal_recharge_is_removed_from_current_behavior() -> None:
    executor = _ImmediateRechargeExecutor()
    runtime = BehaviorRuntime(executor)
    runtime.blackboard.need_module.set_need("Energy", 95)
    runtime.candidate_pool.add(
        "recharge",
        0,
        value=95,
        need_type="physiological",
        candidate_id="recharge-candidate-1",
    )

    started = runtime.tick()
    assert started.started_behavior is not None
    assert runtime.blackboard.current_behavior.behavior_name == "recharge"

    executor.return_result = True
    completed = runtime.tick()
    assert completed.completed_event is not None
    assert completed.completed_event.metadata == {"energyValue": 88}
    assert runtime.blackboard.current_behavior is None
    assert runtime.blackboard.current_goal_id is None


def test_recharge_navigation_uses_long_timeout_and_blocks_emotion_preemption() -> None:
    mapper = IntentMapper()
    candidate = mapper.map_need_event(
        "NEED_ENERGY_OVERFLOW",
        {"demand": "Energy", "value": 95, "level": "OVERFLOW"},
    )
    assert candidate is not None
    pool_candidate = candidate.to_pool_dict()
    assert pool_candidate["priority_level"] == 0
    assert pool_candidate["timeout_sec"] == 330.0

    executor = _ImmediateRechargeExecutor()
    runtime = BehaviorRuntime(executor)
    runtime.blackboard.need_module.set_need("Energy", 95)
    runtime.candidate_pool.add(**pool_candidate)
    runtime.tick()

    assert runtime.blackboard.current_behavior is not None
    assert runtime.blackboard.current_behavior.behavior_name == "recharge"

    # Six seconds used to exceed the generic Lv0 timeout (5 s), cancel Nav2,
    # and let the queued emotion execute.  Recharge must remain authoritative.
    runtime.blackboard._behavior_start_time = time.time() - 6.0
    runtime.blackboard.emotion_module.update_state("Joy", 90, True)
    runtime.candidate_pool.add(
        "expressJoyAlone",
        5,
        value=90,
        need_type="emotional",
        source_emotion="Joy",
        params={
            "source": "emotion",
            "source_emotion": "Joy",
            "visual_resolved": True,
        },
        candidate_id="emotion-candidate-during-recharge",
    )

    outcome = runtime.tick()

    assert outcome.completed_event is None
    assert runtime.blackboard.timeout_occurred is False
    assert runtime.blackboard.current_behavior is not None
    assert runtime.blackboard.current_behavior.behavior_name == "recharge"
    assert executor.canceled_goal_ids == []


def test_low_energy_rest_navigation_does_not_inherit_five_second_timeout() -> None:
    candidate = IntentMapper().map_need_event(
        "NEED_ENERGY_TRIGGERED",
        {"demand": "Energy", "value": 81, "level": "TRIGGERED"},
    )

    assert candidate is not None
    pool_candidate = candidate.to_pool_dict()
    assert pool_candidate["behavior_name"] == "restInPlace"
    assert pool_candidate["priority_level"] == 0
    assert pool_candidate["timeout_sec"] == 330.0


def test_hunger_waits_for_recharge_then_runs_from_delayed_queue() -> None:
    mapper = IntentMapper()
    recharge = mapper.map_need_event(
        "NEED_ENERGY_OVERFLOW",
        {"demand": "Energy", "value": 95, "level": "OVERFLOW"},
    )
    hunger = mapper.map_need_event(
        "NEED_HUNGER_TRIGGERED",
        {
            "demand": "Hunger",
            "value": 80,
            "level": "TRIGGERED",
            "visual_route": "dog_food",
            "target": {
                "target_type": "object",
                "target_id": "food-1",
                "object_category": "food_bowl",
            },
        },
    )
    assert recharge is not None
    assert hunger is not None
    assert hunger.to_pool_dict()["ttl_sec"] == 0.0

    executor = _ControlledQueueExecutor()
    runtime = BehaviorRuntime(executor)
    runtime.blackboard.need_module.set_need("Energy", 95)
    runtime.blackboard.need_module.set_need("Hunger", 80)
    runtime.candidate_pool.add(**recharge.to_pool_dict())

    recharge_started = runtime.tick()
    assert recharge_started.started_behavior is not None
    assert recharge_started.started_behavior.behavior_name == "recharge"

    runtime.candidate_pool.add(**hunger.to_pool_dict())
    waiting = runtime.tick()

    assert waiting.selected_candidate is None
    assert runtime.candidate_pool.size() == 1
    assert runtime.candidate_pool.candidates[0]["behavior_name"] == "eatNormally"
    assert runtime.blackboard.current_behavior.behavior_name == "recharge"
    assert executor.canceled_goal_ids == []

    executor.completed.add(runtime.blackboard.current_goal_id)
    recharge_completed = runtime.tick()
    assert recharge_completed.completed_event is not None
    assert recharge_completed.completed_event.behavior_name == "recharge"
    assert runtime.candidate_pool.size() == 1

    hunger_started = runtime.tick()
    assert hunger_started.selected_candidate is not None
    assert hunger_started.selected_candidate["behavior_name"] == "eatNormally"
    assert hunger_started.started_behavior is not None
    assert hunger_started.started_behavior.behavior_name == "eatNormally"
    assert runtime.candidate_pool.size() == 0
