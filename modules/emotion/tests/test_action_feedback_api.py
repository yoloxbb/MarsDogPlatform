import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class ActionFeedbackAPITest(unittest.TestCase):
    def test_current_action_command_is_stable_until_feedback(self):
        """同一个具体动作未反馈完成前应复用同一个命令 ID。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)

        firstCommand = system.GetCurrentActionCommand()
        secondCommand = system.GetCurrentActionCommand()
        system.Tick(currentTime=22)
        thirdCommand = system.GetCurrentActionCommand()

        self.assertIsNotNone(firstCommand)
        self.assertEqual(firstCommand, secondCommand)
        self.assertEqual(firstCommand, thirdCommand)
        self.assertEqual(firstCommand["topAction"], "ACTION_EAT")
        self.assertEqual(firstCommand["concreteAction"], "ACT_RUN_TO_BOWL")
        self.assertEqual(system.GetDemandValue("Hunger"), 80)

    def test_success_feedback_advances_behavior_tree_and_applies_result_once_finished(self):
        """成功反馈应推进具体动作，整棵行为树完成后才回写需求值。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)

        firstCommand = system.GetCurrentActionCommand()
        self.assertTrue(system.OnActionFeedback(firstCommand["commandId"], firstCommand["concreteAction"], "SUCCESS"))

        secondCommand = system.GetCurrentActionCommand()
        self.assertIsNotNone(secondCommand)
        self.assertNotEqual(firstCommand["commandId"], secondCommand["commandId"])
        self.assertEqual(secondCommand["stepIndex"], 1)
        self.assertEqual(system.GetDemandValue("Hunger"), 80)

        for _ in range(20):
            command = system.GetCurrentActionCommand()
            if command is None:
                break
            self.assertTrue(system.OnActionFeedback(command["commandId"], command["concreteAction"], "SUCCESS"))

        self.assertEqual(system.GetDemandValue("Hunger"), 60)
        self.assertIsNone(system.GetCurrentActionCommand())

    def test_finished_same_action_can_restart_when_demand_is_still_active(self):
        """同一行为已结束但需求仍超阈值时，下一轮仲裁应允许重新启动。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 95)
        system.Tick(currentTime=22)

        for _ in range(10):
            command = system.GetCurrentActionCommand()
            if command is None:
                break
            self.assertTrue(system.OnActionFeedback(command["commandId"], command["concreteAction"], "SUCCESS"))

        self.assertEqual(system.GetDemandValue("Hunger"), 75)
        self.assertIsNone(system.GetCurrentActionCommand())

        system.Tick(currentTime=22)
        restartedCommand = system.GetCurrentActionCommand()

        self.assertIsNotNone(restartedCommand)
        self.assertEqual(restartedCommand["topAction"], "ACTION_EAT")
        self.assertEqual(restartedCommand["stepIndex"], 0)

    def test_interrupted_feedback_applies_interrupted_demand_delta(self):
        """中断反馈应结束当前行为树并执行需求被打断规则。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        command = system.GetCurrentActionCommand()

        self.assertTrue(system.OnActionFeedback(command["commandId"], command["concreteAction"], "INTERRUPTED"))

        self.assertEqual(system.GetCurrentAction(), "ACTION_LOAF")
        self.assertEqual(system.GetDemandValue("Hunger"), 60)
        self.assertEqual(system.GetCurrentBehaviorTreeStatus(), "FAILURE")
        self.assertEqual(system.state.lastActionFeedbackStatus, "INTERRUPTED")

    def test_failure_feedback_releases_current_action_without_lowering_demand(self):
        """失败反馈应释放当前行为，等待下一轮仲裁重试。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        command = system.GetCurrentActionCommand()

        self.assertTrue(system.OnActionFeedback(command["commandId"], command["concreteAction"], "FAILURE"))

        self.assertEqual(system.GetCurrentAction(), "ACTION_LOAF")
        self.assertEqual(system.GetDemandValue("Hunger"), 80)
        system.Tick(currentTime=22)
        self.assertEqual(system.GetCurrentAction(), "ACTION_EAT")

    def test_stale_feedback_is_rejected(self):
        """过期或不匹配的反馈不应推进行为树。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        command = system.GetCurrentActionCommand()

        self.assertFalse(system.OnActionFeedback("wrong-command", command["concreteAction"], "SUCCESS"))
        self.assertFalse(system.OnActionFeedback(command["commandId"], "WRONG_ACTION", "SUCCESS"))
        self.assertEqual(system.GetCurrentActionCommand(), command)


if __name__ == "__main__":
    unittest.main()
