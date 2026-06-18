import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class EnergyBehaviorTest(unittest.TestCase):
    def test_set_energy_battery_value_clamps_range(self):
        """硬件电量写入时应限制在 0-100。"""
        system = MarsdogBehaviorSystem()

        self.assertTrue(system.SetEnergyBatteryValue(150))
        self.assertEqual(system.GetBatteryValue(), 100)

        self.assertTrue(system.SetEnergyBatteryValue(-1))
        self.assertEqual(system.GetBatteryValue(), 0)

    def test_initialize_morning_energy_uses_full_battery(self):
        """晨起精力值应初始化为满电。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 10)

        value = system.InitializeMorningEnergy()

        self.assertEqual(value, 100)
        self.assertEqual(system.GetDemandValue("Energy"), 100)

    def test_energy_under_20_triggers_recharge_by_priority_table(self):
        """按优先级表，Energy < 20 应触发充电。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 19)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_RECHARGE")

    def test_energy_equal_20_does_not_trigger_recharge(self):
        """Energy 等于 20 时尚未低于触发阈值。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 20)

        system.Tick(currentTime=22)

        self.assertNotEqual(system.GetCurrentAction(), "ACTION_RECHARGE")

    def test_energy_priority_beats_bladder_priority(self):
        """Lv.0 低电量应优先于 Lv.1 排泄。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 19)
        system.SetDemandValue("Bladder", 76)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_RECHARGE")

    def test_danger_event_beats_recharge_priority(self):
        """同为 Lv.0 时危险事件分数更高，应优先生存避险。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 5)
        system.OnEnvironmentChange("danger", 70)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")

    def test_low_energy_behavior_tree_randomly_selects_one_action(self):
        """Energy < 20 时应从低电量动作池随机抽 1 个动作。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Energy", 15)
        steps = system.GetActionSequence("ACTION_RECHARGE")

        self.assertEqual(len(steps), 1)
        self.assertIn(
            steps[0],
            {
                "ACT_PANT_IN_PLACE",
                "ACT_RESIST_WALKING",
                "ACT_SLOW_MOVEMENT",
            },
        )

    def test_critical_energy_behavior_tree_uses_charger_sequence(self):
        """Energy < 10 时应优先展开严重低电量动作。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Energy", 5)
        steps = system.GetActionSequence("ACTION_RECHARGE")

        self.assertEqual(
            steps,
            ["ACT_RETURN_TO_CHARGER", "ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER"],
        )

    def test_execute_recharge_restores_energy_to_target(self):
        """执行充电行为应恢复到配置目标电量。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Energy", 15)

        self.assertTrue(system.ExecuteRecharge())

        self.assertEqual(system.GetDemandValue("Energy"), 100)
        self.assertGreater(system.GetEmotionValue("Joy"), 0)

    def test_recharge_behavior_tree_success_applies_recharge_result_once(self):
        """ACTION_RECHARGE 行为树成功后应只回写一次充电结果。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Energy", 15)
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
        self.assertEqual(system.GetDemandValue("Energy"), 100)

        system.TickCurrentBehaviorTree()
        self.assertEqual(system.GetDemandValue("Energy"), 100)


if __name__ == "__main__":
    unittest.main()
