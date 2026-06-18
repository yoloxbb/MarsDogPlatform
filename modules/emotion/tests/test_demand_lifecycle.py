import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class DemandLifecycleTest(unittest.TestCase):
    def test_midnight_lock_skips_natural_demand_growth(self):
        """凌晨锁定时段不参与自然需求计算。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 70)

        system.Tick(currentTime=2)

        self.assertTrue(system.state.demandLockActive)
        self.assertEqual(system.GetDemandValue("Hunger"), 70)

    def test_six_oclock_resets_all_demands_to_morning_values(self):
        """06:00 后应恢复所有需求到晨起初始值。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(4))
        system.SetDemandValue("Hunger", 95)
        system.SetDemandValue("Bladder", 90)
        system.SetDemandValue("Cleanliness", 20)

        system.Tick(currentTime=2)
        system.Tick(currentTime=6)

        self.assertGreaterEqual(system.GetDemandValue("Hunger"), 60)
        self.assertLessEqual(system.GetDemandValue("Hunger"), 70)
        self.assertGreaterEqual(system.GetDemandValue("Bladder"), 20)
        self.assertLessEqual(system.GetDemandValue("Bladder"), 30)
        self.assertGreaterEqual(system.GetDemandValue("Cleanliness"), 5)
        self.assertLessEqual(system.GetDemandValue("Cleanliness"), 15)

    def test_morning_reset_only_runs_once_without_new_lock_period(self):
        """同一个无日期测试日内晨起重置只执行一次。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(4))

        system.Tick(currentTime=2)
        system.Tick(currentTime=6)
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=8)

        self.assertEqual(system.GetDemandValue("Hunger"), 81)

    def test_interrupted_internal_demand_reduces_demand_once_and_applies_emotion(self):
        """内部需求被高优先级事件打断时需求值 -20 并触发情绪映射。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)

        system.Tick(currentTime=22)
        system.SetDemandValue("Social", 80)
        system.OnVoiceInput("OwnerCall", "front", 1.0)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_SOCIAL_GREET")
        self.assertEqual(system.state.previousDemandType, "Hunger")
        self.assertEqual(system.GetDemandValue("Hunger"), 60)
        self.assertGreaterEqual(system.GetEmotionValue("Anxiety"), 3)

    def test_external_action_interruption_does_not_reduce_internal_demand(self):
        """外部交互行为被打断时不应误扣内部需求值。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Social", 80)
        system.OnVoiceInput("OwnerCall", "front", 1.0)
        system.Tick(currentTime=22)

        system.OnEnvironmentChange("danger", 70)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")
        self.assertEqual(system.GetDemandValue("Social"), 80)


if __name__ == "__main__":
    unittest.main()
