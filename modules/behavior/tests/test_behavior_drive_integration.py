"""Direct and internal triggers share execution but not state ownership."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.conditions import BehaviorRelevanceCondition
from bionic_dog_bt.constants import GOAL_CANCEL_REQUESTED, GOAL_RUNNING, GOAL_TERMINAL
from bionic_dog_bt.datatypes import ActiveBehavior, BehaviorFeedbackEvent, ExecutorFeedback
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.interaction_resolver import InteractionResolver
from marsdog_behavior.relevance_checker import is_behavior_relevant
from marsdog_behavior.ros_node import BehaviorTreeRosNode
from marsdog_behavior.runtime import BehaviorRuntime


DIRECT = ("audio_direct", "audio_reaction", "audio_session", "visual_direct", "touch_direct")


def active(source, *, need_type="emotional", name="expressJoyAlone", priority=5, identity="goal"):
    return ActiveBehavior(identity, name, priority, 70, 1, need_type, timeout_sec=0,
                          params={"source": source, "source_emotion": "Joy",
                                  "source_need": "Hunger"})


class Executor:
    """Cancel acknowledges immediately; only complete() supplies a terminal."""
    def __init__(self):
        self.sent, self.canceled, self.removed = [], [], []
        self.goals, self.lifecycle, self.results = {}, {}, {}

    def send_goal(self, behavior):
        self.sent.append(behavior)
        self.goals[behavior.behavior_id] = behavior
        self.lifecycle[behavior.behavior_id] = GOAL_RUNNING
        return behavior.behavior_id

    def cancel_goal(self, goal):
        self.canceled.append(goal)
        self.lifecycle[goal] = GOAL_CANCEL_REQUESTED
        return True

    def tick(self): pass
    def has_goal(self, goal): return goal in self.goals
    def get_goal_lifecycle(self, goal): return self.lifecycle.get(goal)
    def get_result(self, goal): return self.results.pop(goal, None)

    def get_feedback(self, goal):
        behavior = self.goals.get(goal)
        return (ExecutorFeedback(behavior.behavior_id, behavior.behavior_name,
                                 "RUNNING", 0.1, safe_to_interrupt=True)
                if behavior else None)

    def remove_goal(self, goal):
        if self.lifecycle.get(goal) == GOAL_TERMINAL:
            self.removed.append(goal)
            self.goals.pop(goal, None)

    def complete(self, goal, status="CANCELED"):
        behavior = self.goals[goal]
        self.lifecycle[goal] = GOAL_TERMINAL
        self.results[goal] = BehaviorFeedbackEvent(
            goal, behavior.behavior_name, status, status.lower(), "actual test terminal")


def node_for_tick(*, started=None, current=None, completed=None):
    methods = ("_renew_action_goal_lease", "_expire_wake_identity_if_due",
               "_expire_wake_target_query_if_due", "_renew_voice_hold_if_due",
               "_dispatch_due_emotion_continuation", "_flush_pending_emotions",
               "_handle_voice_behavior_terminal", "_schedule_emotion_continuation",
               "_publish_result", "_publish_started")
    return NS(**{name: Mock() for name in methods},
              _blackboard=NS(current_behavior=current),
              _emotion_continuations={"Joy": {"cycles": 2}},
              _runtime=NS(tick=lambda: NS(started_behavior=started, completed_event=completed)))


class DriveIntegrationTests(unittest.TestCase):
    def test_direct_templates_do_not_require_an_internal_emotion_signal(self):
        for source in DIRECT:
            with self.subTest(source=source):
                bb = Blackboard()
                bb.active_behavior = active(source)
                condition = BehaviorRelevanceCondition("relevant", bb)
                self.assertEqual(condition.update(), Status.SUCCESS)
                self.assertIsNotNone(bb.active_behavior)

    def test_internal_emotion_is_checked_even_when_priority_category_changes(self):
        bb = Blackboard()
        bb.active_behavior = active("emotion", need_type="external", priority=1)
        self.assertEqual(BehaviorRelevanceCondition("relevant", bb).update(), Status.FAILURE)
        self.assertIsNone(bb.active_behavior)

    def test_explicit_need_source_owns_relevance_instead_of_expression_style(self):
        bb = Blackboard()
        bb.need_module.is_triggered = Mock(return_value=True)
        bb.active_behavior = active("need")
        self.assertEqual(BehaviorRelevanceCondition("relevant", bb).update(), Status.SUCCESS)
        bb.need_module.is_triggered.return_value = False
        self.assertEqual(BehaviorRelevanceCondition("relevant", bb).update(), Status.FAILURE)

    def test_helper_and_real_tree_use_the_same_state_rule_without_mutating_payload(self):
        for source, need_type in (("audio_reaction", "emotional"), ("emotion", "external"),
                                  ("need", "system"), ("", "emotional")):
            with self.subTest(source=source):
                bb = Blackboard()
                behavior = active(source, need_type=need_type)
                payload = {"behavior_name": behavior.behavior_name,
                           "need_type": need_type, "params": behavior.params}
                before = deepcopy(payload)
                relevant = is_behavior_relevant(payload, bb)
                bb.active_behavior = behavior
                status = BehaviorRelevanceCondition("relevant", bb).update()
                self.assertEqual(relevant, status == Status.SUCCESS)
                self.assertEqual(payload, before)

    def test_recovered_state_does_not_stop_an_already_running_behavior(self):
        bb = Blackboard()
        bb.start_behavior(active("emotion"), "goal")
        self.assertEqual(BehaviorRelevanceCondition("relevant", bb).update(), Status.SUCCESS)
        self.assertEqual(bb.current_goal_id, "goal")

    def test_recovery_discards_only_the_internal_emotion_candidate(self):
        pool = CandidatePool()
        pool.add("direct-expression", 5, need_type="emotional", source_emotion="Joy",
                 params={"source": "touch_direct", "source_emotion": "Joy"})
        pool.add("internal-expression", 1, need_type="external", source_emotion="Joy",
                 params={"source": "emotion", "source_emotion": "Joy"})
        self.assertEqual(pool.discard_emotion("Joy"), 1)
        self.assertEqual([c["behavior_name"] for c in pool.candidates], ["direct-expression"])

    def test_need_recovery_does_not_remove_a_direct_command_using_need_metadata(self):
        pool = CandidatePool()
        for source, name in (("need", "internal-eat"), ("audio_direct", "command-eat")):
            pool.add(name, 3, need_type="physiological", params={
                "source": source, "source_need": "Hunger", "trigger_event": "old"})
        self.assertEqual(pool.discard_need_except("Hunger", "new"), 1)
        self.assertEqual([c["behavior_name"] for c in pool.candidates], ["command-eat"])

    def test_direct_goal_keeps_its_resolved_target_and_never_requeries_person(self):
        for source in DIRECT:
            with self.subTest(source=source):
                executor = Executor()
                runtime = BehaviorRuntime(executor)
                runtime.blackboard.emotion_module.set_triggered("Joy", True)
                perception = Mock()
                perception.check_person.return_value = {"present": False}
                runtime.blackboard.perception_client = perception
                params = {"source": source, "source_emotion": "Joy", "interactive": True,
                          "target": {"target_id": "bound-person", "target_type": "human"}}
                runtime.candidate_pool.add("direct-template", 5, need_type="emotional", params=params)
                outcome = runtime.tick()
                self.assertIsNotNone(outcome.started_behavior)
                self.assertEqual(executor.sent[0].params["target"], params["target"])
                perception.check_person.assert_not_called()

    def test_internal_unresolved_target_still_uses_the_compatibility_query(self):
        executor = Executor()
        runtime = BehaviorRuntime(executor)
        runtime.blackboard.emotion_module.set_triggered("Joy", True)
        perception = Mock()
        perception.check_person.return_value = {"present": True, "identity": "owner"}
        runtime.blackboard.perception_client = perception
        runtime.candidate_pool.add("internal-template", 1, need_type="external",
                                   params={"source": "emotion", "source_emotion": "Joy"})
        runtime.tick()
        perception.check_person.assert_called_once()
        self.assertEqual(executor.sent[0].params["target"]["target_id"], "owner")

    def test_compatibility_interaction_resolver_preserves_every_direct_source(self):
        perception = Mock()
        perception.check_person.return_value = {"present": False}
        resolver = InteractionResolver(perception)
        for source in DIRECT:
            params = {"source": source, "interactive": True, "target_identity": "bound"}
            original = dict(params)
            self.assertEqual(resolver.resolve_interaction("template", params, "emotional"), original)
        perception.check_person.assert_not_called()

    def test_direct_expression_does_not_consume_internal_continuation_cycles(self):
        node = node_for_tick(started=active("audio_reaction", need_type="external"))
        BehaviorTreeRosNode._on_tick(node)
        self.assertEqual(node._emotion_continuations["Joy"]["cycles"], 2)
        node._publish_started.assert_called_once()

    def test_direct_terminal_does_not_reschedule_internal_continuation(self):
        current = active("audio_reaction", need_type="external")
        for status in ("SUCCESS", "CANCELED", "FAILED"):
            with self.subTest(status=status):
                result = NS(behavior_id="goal", behavior_name=current.behavior_name, status=status)
                node = node_for_tick(current=current, completed=result)
                BehaviorTreeRosNode._on_tick(node)
                node._schedule_emotion_continuation.assert_not_called()
                node._handle_voice_behavior_terminal.assert_called_once_with(current, result)
                node._publish_result.assert_called_once()

    def test_internal_continuation_keeps_start_and_terminal_observations(self):
        current = active("emotion", need_type="external")
        node = node_for_tick(started=current)
        BehaviorTreeRosNode._on_tick(node)
        self.assertEqual(node._emotion_continuations["Joy"]["cycles"], 3)
        result = NS(behavior_id="goal", behavior_name=current.behavior_name, status="SUCCESS")
        node = node_for_tick(current=current, completed=result)
        BehaviorTreeRosNode._on_tick(node)
        node._schedule_emotion_continuation.assert_called_once_with("Joy", "SUCCESS")

    def test_direct_preemption_waits_for_internal_goal_terminal(self):
        executor = Executor()
        runtime = BehaviorRuntime(executor)
        runtime.blackboard.emotion_module.set_triggered("Joy", True)
        pool = runtime.candidate_pool
        pool.add("internal-expression", 5, candidate_id="internal", need_type="emotional",
                 params={"source": "emotion", "source_emotion": "Joy", "visual_resolved": True})
        runtime.tick()
        pool.add("direct-command", 1, candidate_id="direct", params={"source": "audio_direct"})
        runtime.tick()
        self.assertEqual(executor.canceled, ["internal"])
        self.assertEqual([b.behavior_id for b in executor.sent], ["internal"])
        self.assertTrue(pool.is_inflight("internal-expression"))
        runtime.tick()
        self.assertEqual(len(executor.sent), 1)
        executor.complete("internal")
        runtime.tick()
        self.assertEqual([b.behavior_id for b in executor.sent], ["internal"])
        self.assertFalse(pool.is_inflight("internal-expression"))
        runtime.tick()
        self.assertEqual([b.behavior_id for b in executor.sent], ["internal", "direct"])
        self.assertFalse(pool.is_inflight("internal-expression"))

    def test_low_priority_direct_work_cannot_bypass_an_internal_goal(self):
        executor = Executor()
        runtime = BehaviorRuntime(executor)
        runtime.blackboard.emotion_module.set_triggered("Joy", True)
        runtime.candidate_pool.add("internal", 4, params={
            "source": "emotion", "source_emotion": "Joy", "visual_resolved": True})
        runtime.tick()
        runtime.candidate_pool.add("direct", 5, params={"source": "touch_direct"})
        runtime.tick()
        self.assertEqual(executor.canceled, [])
        self.assertEqual([b.behavior_name for b in executor.sent], ["internal"])
        self.assertEqual(runtime.candidate_pool.size(), 1)

    def test_urgent_internal_need_can_preempt_a_direct_goal(self):
        executor = Executor()
        runtime = BehaviorRuntime(executor)
        runtime.blackboard.need_module.is_triggered = Mock(return_value=True)
        runtime.candidate_pool.add("direct", 1, candidate_id="direct",
                                   params={"source": "audio_direct"})
        runtime.tick()
        runtime.candidate_pool.add("urgent-internal", 0, params={
            "source": "need", "source_need": "Energy"})
        runtime.tick()
        self.assertEqual(executor.canceled, ["direct"])
        self.assertEqual([b.behavior_name for b in executor.sent], ["direct"])
        self.assertTrue(runtime.candidate_pool.is_inflight("direct"))


if __name__ == "__main__":
    unittest.main()
