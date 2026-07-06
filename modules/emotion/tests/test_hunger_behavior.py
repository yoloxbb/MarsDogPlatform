import random
import unittest

from marsdog_core import MarsdogNeedSystem


class HungerBehaviorTest(unittest.TestCase):
    def test_initialize_morning_hunger_uses_range(self):
        """饥渴晨起值应在 60-70 随机范围内。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningHunger()

        self.assertTrue(60 <= value <= 70)
        self.assertEqual(system.GetDemandValue("Hunger"), value)

    def test_hunger_grows_only_in_daytime(self):
        """饥渴值白天每 Tick +1，其他时间不增长。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 65)

        system.UpdateHungerByTime(8)
        self.assertEqual(system.GetDemandValue("Hunger"), 66)
        system.UpdateHungerByTime(22)
        self.assertEqual(system.GetDemandValue("Hunger"), 66)

    def test_hunger_recovery_formula(self):
        """进食恢复值应按食物类型、份数和效率计算。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetHungerRecoveryValue("PremiumFood", 2, "Full"), 60)
        self.assertEqual(system.GetHungerRecoveryValue("NormalFood", 1, "HalfInterrupted"), 10)
        self.assertEqual(system.GetHungerRecoveryValue("Snack", 2, "Full"), 10)

    def test_execute_eat_updates_linked_demands(self):
        """进食会降低 Hunger，并联动 Bladder 和 Cleanliness。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 95)
        system.SetDemandValue("Bladder", 0)
        system.SetDemandValue("Cleanliness", 10)

        self.assertTrue(system.ExecuteEat("NormalFood", 1, "Full"))

        self.assertEqual(system.GetDemandValue("Hunger"), 75)
        self.assertEqual(system.GetDemandValue("Bladder"), 25)
        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)

    def test_behavior_result_event_eat_completed(self):
        """行为组回传 ACTION_EAT 完成时应执行同样需求结算。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Bladder", 0)
        system.SetDemandValue("Cleanliness", 10)

        accepted = system.OnBehaviorResultEvent(
            {
                "action_type": "ACTION_EAT",
                "result_type": "COMPLETED",
                "metadata": {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"},
            }
        )

        self.assertTrue(accepted)
        self.assertEqual(system.GetDemandValue("Hunger"), 60)
        self.assertEqual(system.GetDemandValue("Bladder"), 20)
        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)


if __name__ == "__main__":
    unittest.main()
