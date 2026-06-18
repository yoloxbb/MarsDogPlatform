import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class HungerBehaviorTest(unittest.TestCase):
    def test_initialize_morning_hunger_uses_random_range(self):
        """晨起饥渴值应落在 60-70。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningHunger()

        self.assertGreaterEqual(value, 60)
        self.assertLessEqual(value, 70)
        self.assertEqual(system.GetDemandValue("Hunger"), value)

    def test_daytime_tick_increases_hunger(self):
        """白天每 10 分钟 Tick 应让 Hunger 增加 1。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 65)

        system.UpdateNaturalDemandsByTime(currentTime=8)

        self.assertEqual(system.GetDemandValue("Hunger"), 66)

    def test_night_tick_does_not_increase_hunger(self):
        """其他时间 Tick 不增加 Hunger。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 65)

        system.UpdateNaturalDemandsByTime(currentTime=22)

        self.assertEqual(system.GetDemandValue("Hunger"), 65)

    def test_hunger_over_70_triggers_eat_after_tick(self):
        """Hunger 经 Tick 增长到大于 70 后应触发进食。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 70)

        system.Tick(currentTime=8)

        self.assertEqual(system.GetCurrentAction(), "ACTION_EAT")

    def test_execute_eat_reduces_hunger_by_food_recovery(self):
        """普通粮一份吃满应恢复 20 点饥渴值。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)

        self.assertTrue(system.ExecuteEat("普通粮", portions=1, eatEfficiency="吃满时长"))

        self.assertEqual(system.GetDemandValue("Hunger"), 60)
        self.assertGreater(system.GetEmotionValue("Joy"), 0)

    def test_execute_eat_unsatisfied_when_food_is_not_enough(self):
        """食物不足导致仍超过阈值时应累积焦虑。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 95)

        self.assertTrue(system.ExecuteEat("零食", portions=1, eatEfficiency="吃满时长"))

        self.assertEqual(system.GetDemandValue("Hunger"), 90)
        self.assertGreater(system.GetEmotionValue("Anxiety"), 0)

    def test_execute_eat_half_interrupted_uses_half_efficiency(self):
        """吃一半被打断时应按 0.5 效率恢复并施加打断情绪。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)

        self.assertTrue(system.ExecuteEat("优质粮", portions=1, eatEfficiency="吃一半被打断"))

        self.assertEqual(system.GetDemandValue("Hunger"), 65)
        self.assertGreaterEqual(system.GetEmotionValue("Anxiety"), 3)


if __name__ == "__main__":
    unittest.main()
