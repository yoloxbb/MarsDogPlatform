import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class BehaviorTreeTest(unittest.TestCase):
    def test_eat_behavior_tree_runs_normal_eat_actions_in_order(self):
        """正常进食行为树应先执行冲向食盆，再执行随机组合动作。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)

        status = system.TickCurrentBehaviorTree()

        self.assertEqual(status, "RUNNING")
        self.assertEqual(system.GetCurrentConcreteAction(), "ACT_RUN_TO_BOWL")

        self.assertTrue(system.MarkCurrentConcreteActionDone())
        system.TickCurrentBehaviorTree()

        self.assertNotEqual(system.GetCurrentConcreteAction(), "ACT_RUN_TO_BOWL")
        self.assertEqual(system.GetFinishedConcreteActions(), ["ACT_RUN_TO_BOWL"])

    def test_eat_behavior_tree_uses_excited_branch_when_hunger_over_90(self):
        """Hunger 大于 90 时应进入激动进食分支。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 95)
        system.Tick(currentTime=22)

        status = system.TickCurrentBehaviorTree()

        self.assertEqual(status, "RUNNING")
        self.assertEqual(system.GetCurrentConcreteAction(), "ACT_RUN_TO_BOWL")

        self.assertTrue(system.MarkCurrentConcreteActionDone())
        system.TickCurrentBehaviorTree()

        self.assertEqual(system.GetCurrentConcreteAction(), "ACT_FAST_LICK_AND_SWALLOW")

    def test_eat_behavior_tree_success_applies_eat_result_once(self):
        """进食行为树完成后应回写一次饥渴结果。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)

        finalStatus = ""
        for _ in range(100):
            finalStatus = system.TickCurrentBehaviorTree()
            currentAction = system.GetCurrentConcreteAction()
            if currentAction:
                system.MarkCurrentConcreteActionDone()
            if finalStatus == "SUCCESS":
                break

        self.assertEqual(finalStatus, "SUCCESS")
        self.assertEqual(system.GetDemandValue("Hunger"), 60)

        system.TickCurrentBehaviorTree()
        self.assertEqual(system.GetDemandValue("Hunger"), 60)

    def test_interruption_marks_current_behavior_tree_failed(self):
        """高优先级行为打断进食时应中断当前行为树。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        system.TickCurrentBehaviorTree()

        self.assertEqual(system.GetCurrentConcreteAction(), "ACT_RUN_TO_BOWL")

        system.SetDemandValue("Social", 80)
        system.OnVoiceInput("OwnerCall", "front", 1.0)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_SOCIAL_GREET")
        self.assertEqual(system.GetCurrentConcreteAction(), "")
        self.assertEqual(system.GetDemandValue("Hunger"), 60)


if __name__ == "__main__":
    unittest.main()
