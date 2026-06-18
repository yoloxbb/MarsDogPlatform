import unittest

from marsdog_core import MarsdogBehaviorSystem


class ArbiterTest(unittest.TestCase):
    def test_level_zero_interrupts_lower_levels(self):
        """Lv.0 命中时应跳过后续层级。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 90)
        system.OnEnvironmentChange("danger", 70)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")

    def test_level_one_beats_level_three(self):
        """Lv.1 生理紧急应抢占 Lv.3 生理常规。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Bladder", 76)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_DEFECATE")

    def test_level_two_interrupts_level_three(self):
        """主人呼唤应中断正在执行的进食行为。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        self.assertEqual(system.GetCurrentAction(), "ACTION_EAT")

        system.SetDemandValue("Social", 80)
        system.OnVoiceInput("OwnerCall", "front", 1.0)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_SOCIAL_GREET")
        self.assertEqual(system.state.previousAction, "ACTION_EAT")

    def test_idle_when_no_rule_matched(self):
        """没有活跃需求或情绪时应输出空闲行为。"""
        system = MarsdogBehaviorSystem()

        system.Tick()

        self.assertEqual(system.GetCurrentAction(), "ACTION_LOAF")

    def test_same_action_requests_are_merged(self):
        """同一行为多次请求应合并为单项队列。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetActionQueue(), ["ACTION_EAT"])


if __name__ == "__main__":
    unittest.main()
