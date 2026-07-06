import random
import unittest

from marsdog_core import MarsdogNeedSystem


class DemandLifecycleTest(unittest.TestCase):
    def test_midnight_lock_skips_normal_demand_growth(self):
        """凌晨锁定期间普通需求不自然增长。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 65)

        system.UpdateNaturalDemandsByTime(2)

        self.assertEqual(system.GetDemandValue("Hunger"), 65)
        self.assertTrue(system.state.demandLockActive)

    def test_sleepiness_is_exception_during_midnight_lock(self):
        """凌晨锁定期间 Sleepiness 仍按强制睡眠规则更新。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.UpdateNaturalDemandsByTime(2)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)

    def test_morning_reset_after_lock(self):
        """06:00 后应执行晨起初始值重置。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(4))
        system.state.lastDemandLockState = True
        system.SetDemandValue("Hunger", 99)
        system.SetDemandValue("Bladder", 99)

        demands = system.UpdateNaturalDemandsByTime(6)

        self.assertTrue(60 <= demands["Hunger"] <= 70)
        self.assertTrue(20 <= demands["Bladder"] <= 30)
        self.assertEqual(system.state.lastMorningResetKey, "static-day")

    def test_interrupted_demand_delta_uses_global_default(self):
        """内部需求被打断时按配置扣减需求值。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)

        self.assertTrue(system.ApplyInterruptedDemandDelta("Hunger"))

        self.assertEqual(system.GetDemandValue("Hunger"), 60)

    def test_action_to_demand_mapping_is_available_for_result_events(self):
        """行为组结果事件可通过 actionDemandMap 找到需求类型。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetDemandTypeByAction("ACTION_EAT"), "Hunger")
        self.assertEqual(system.GetDemandTypeByAction("ACTION_SLEEP"), "Sleepiness")
        self.assertIsNone(system.GetDemandTypeByAction("ACTION_UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
