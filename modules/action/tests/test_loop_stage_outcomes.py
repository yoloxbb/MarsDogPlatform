"""Loop stage outcome and cancellation must reflect actual unit execution."""
import unittest
from unittest.mock import Mock, patch

from marsdog_action_executor.execution_context import ExecutionContext
from marsdog_action_executor.stage_executor import StageExecutor
from marsdog_action_executor.result_evaluator import ResultEvaluator


class LoopOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.stage = StageExecutor()
        self.ctx = ExecutionContext(requested_behavior_name="probe", resolved_behavior_name="probe")
        self.stage._select_best = Mock(return_value={"unit_id": "test_unit"})
        self.stage._execute_unit = Mock(return_value=True)
        self.config = {"stage_id": "loop", "selection_policy": "loop_random",
                       "required": True, "failure_policy": "abort",
                       "loop_policy": {"min": 2, "max": 2, "interval_sec": 0}}

    def test_required_failed_unit_cannot_become_successful_behavior(self):
        self.ctx.metadata["unit_failure_reason"] = "controller lost"
        self.stage._execute_unit.return_value = False
        result = self.stage.execute_stage(self.config, self.ctx, seed=0)
        self.assertFalse(result.success)
        self.assertEqual(result.unit_id, "test_unit")
        self.assertEqual(result.message, "controller lost")
        self.stage._execute_unit.assert_called_once()
        self.assertEqual(self.ctx.completed_stages, [])
        self.assertFalse(ResultEvaluator().evaluate(
            self.ctx, {"loop": result.success}, "all_required_stages_completed").success)

    def test_no_eligible_candidate_fails_required_stage(self):
        self.stage._select_best.return_value = None
        result = self.stage.execute_stage(self.config, self.ctx, seed=0)
        self.assertFalse(result.success)
        self.assertIn("no_eligible_action", result.message)
        self.stage._execute_unit.assert_not_called()

    def test_optional_or_skip_policy_does_not_claim_completed_stage(self):
        for changes in ({"required": False}, {"failure_policy": "skip_stage"}):
            with self.subTest(changes=changes):
                self.stage._execute_unit.return_value = False
                result = self.stage.execute_stage({**self.config, **changes}, self.ctx, seed=0)
                self.assertTrue(result.success)
                self.assertEqual(self.ctx.completed_stages, [])

    def test_cancel_before_first_iteration_runs_no_unit_even_if_optional(self):
        self.stage._interrupt.request_cancel()
        result = self.stage.execute_stage({**self.config, "required": False}, self.ctx, seed=0)
        self.assertFalse(result.success)
        self.assertEqual(self.ctx.metadata["unit_failure_state"], "canceled")
        self.stage._execute_unit.assert_not_called()

    def test_cancel_during_interval_prevents_next_unit(self):
        self.config["loop_policy"]["interval_sec"] = 10
        def request_cancel(_seconds):
            self.stage._interrupt.request_cancel()
        with patch("marsdog_action_executor.stage_executor.time.monotonic", return_value=10), \
                patch("marsdog_action_executor.stage_executor.time.sleep", side_effect=request_cancel) as sleep:
            result = self.stage.execute_stage(self.config, self.ctx, seed=0)
        self.assertFalse(result.success)
        self.stage._execute_unit.assert_called_once()
        self.assertLessEqual(sleep.call_args.args[0], 0.05)
        self.assertEqual(self.ctx.completed_stages, [])

    def test_controller_canceled_result_is_not_skipped_as_optional_success(self):
        self.ctx.metadata.update(unit_failure_state="canceled", unit_failure_reason="controller canceled")
        self.stage._execute_unit.return_value = False
        result = self.stage.execute_stage({**self.config, "required": False}, self.ctx, seed=0)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "controller canceled")

    def test_cancel_zero_iterations_does_not_claim_completion(self):
        self.stage._interrupt.request_cancel()
        self.config["loop_policy"].update(min=0, max=0)
        self.assertFalse(self.stage.execute_stage(self.config, self.ctx).success)
        self.assertEqual(self.ctx.completed_stages, [])

    def test_success_and_zero_iteration_policy_keep_existing_behavior(self):
        result = self.stage.execute_stage(self.config, self.ctx, seed=0)
        self.assertTrue(result.success)
        self.assertEqual(self.stage._execute_unit.call_count, 2)
        self.assertEqual(self.ctx.completed_stages, ["loop"])
        self.ctx.completed_stages.clear()
        self.stage._execute_unit.reset_mock()
        self.config["loop_policy"].update(min=0, max=0)
        result = self.stage.execute_stage(self.config, self.ctx, seed=0)
        self.assertTrue(result.success)
        self.stage._execute_unit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
