import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class CleanlinessBehaviorTest(unittest.TestCase):
    def test_initialize_morning_cleanliness_uses_random_range(self):
        """晨起清洁值应落在 5-15。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningCleanliness()

        self.assertGreaterEqual(value, 5)
        self.assertLessEqual(value, 15)
        self.assertEqual(system.GetDemandValue("Cleanliness"), value)

    def test_daytime_tick_increases_cleanliness_by_two(self):
        """白天每 10 分钟 Tick 应让 Cleanliness 增加 2。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Cleanliness", 10)

        system.UpdateNaturalDemandsByTime(currentTime=8)

        self.assertEqual(system.GetDemandValue("Cleanliness"), 12)

    def test_night_tick_does_not_increase_cleanliness(self):
        """其他时间 Tick 不增加 Cleanliness。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Cleanliness", 10)

        system.UpdateNaturalDemandsByTime(currentTime=22)

        self.assertEqual(system.GetDemandValue("Cleanliness"), 10)

    def test_eat_adds_twenty_to_cleanliness(self):
        """进食后应让 Cleanliness 增加 20。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Cleanliness", 10)

        system.ExecuteEat("普通粮", 1, "吃满时长")

        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)

    def test_cleanliness_gt_70_triggers_groom_by_priority_table(self):
        """按优先级表，Cleanliness > 70 应触发清洁。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Cleanliness", 71)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_GROOM")

    def test_cleanliness_equal_70_does_not_trigger_groom(self):
        """Cleanliness 等于 70 时尚未超过触发阈值。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Cleanliness", 70)

        system.Tick(currentTime=22)

        self.assertNotEqual(system.GetCurrentAction(), "ACTION_GROOM")

    def test_cleanliness_priority_beats_hunger_when_value_is_higher(self):
        """Lv.3 同层需求触发时按原始值更高者执行。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Cleanliness", 90)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_GROOM")

    def test_bladder_priority_beats_cleanliness_priority(self):
        """Lv.1 排泄应优先于 Lv.3 清洁。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 76)
        system.SetDemandValue("Cleanliness", 90)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_DEFECATE")

    def test_groom_behavior_tree_randomly_selects_one_action(self):
        """ACTION_GROOM 行为树应只随机抽 1 个处理毛发动作。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Cleanliness", 80)
        steps = system.GetActionSequence("ACTION_GROOM")

        self.assertEqual(len(steps), 1)
        self.assertIn(
            steps[0],
            {
                "ACT_LICK_PAWS_OR_FUR",
                "ACT_SCRATCH",
                "ACT_SHAKE_OFF_WATER",
                "ACT_STRETCH_LAZILY",
                "ACT_ROLL_OVER",
                "ACT_RUB_AGAINST_OBJECT",
                "ACT_PANT",
            },
        )

    def test_execute_groom_reduces_cleanliness_by_fifty(self):
        """执行清洁行为应让 Cleanliness 降低 50。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Cleanliness", 80)

        self.assertTrue(system.ExecuteGroom())

        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)
        self.assertGreater(system.GetEmotionValue("Joy"), 0)

    def test_groom_behavior_tree_success_applies_groom_result_once(self):
        """ACTION_GROOM 行为树成功后应只回写一次清洁结果。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Cleanliness", 80)
        system.Tick(currentTime=22)

        finalStatus = ""
        for _ in range(20):
            finalStatus = system.TickCurrentBehaviorTree()
            currentAction = system.GetCurrentConcreteAction()
            if currentAction:
                system.MarkCurrentConcreteActionDone()
            if finalStatus == "SUCCESS":
                break

        self.assertEqual(finalStatus, "SUCCESS")
        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)

        system.TickCurrentBehaviorTree()
        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)


if __name__ == "__main__":
    unittest.main()
