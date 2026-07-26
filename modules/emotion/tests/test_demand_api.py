import unittest

from marsdog_core import MarsdogNeedSystem


class DemandAPITest(unittest.TestCase):
    def test_get_and_set_demand_value_clamps_range(self):
        """需求写入应统一限制在 0-100。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.SetDemandValue("Hunger", 120))
        self.assertEqual(system.GetDemandValue("Hunger"), 100)
        self.assertTrue(system.SetDemandValue("Hunger", -10))
        self.assertEqual(system.GetDemandValue("Hunger"), 0)

    def test_get_all_demands_returns_copy(self):
        """批量读取需求时不暴露内部 dict。"""
        system = MarsdogNeedSystem()

        demands = system.GetAllDemands()
        demands["Hunger"] = 0

        self.assertNotEqual(system.GetDemandValue("Hunger"), 0)

    def test_is_demand_urgent_uses_config_operator(self):
        """紧急判断应使用配置里的阈值和操作符。"""
        system = MarsdogNeedSystem()

        system.SetDemandValue("Hunger", 71)
        system.SetDemandValue("Energy", 81)

        self.assertTrue(system.IsDemandUrgent("Hunger"))
        self.assertTrue(system.IsDemandUrgent("Energy"))

    def test_get_most_urgent_demand_uses_raw_value_order(self):
        """多个需求触发时按原始值排序，不做紧迫度换算。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Exploration", 90)

        self.assertEqual(system.GetMostUrgentDemand(), "Exploration")

    def test_get_most_urgent_demand_excludes_non_triggered_values(self):
        """原始值较大但未触发的需求不应参与紧迫度比较。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 71)
        system.SetDemandValue("Energy", 80)

        self.assertEqual(system.GetMostUrgentDemand(), "Hunger")

        system.SetDemandValue("Energy", 95)
        self.assertEqual(system.GetMostUrgentDemand(), "Energy")

    def test_get_demand_level_value(self):
        """需求等级应按普通、触发、满溢三档计算。"""
        system = MarsdogNeedSystem()

        system.SetDemandValue("Hunger", 70)
        self.assertEqual(system.GetDemandLevelValue("Hunger")["level"], "NORMAL")
        system.SetDemandValue("Hunger", 71)
        self.assertEqual(system.GetDemandLevelValue("Hunger")["level"], "TRIGGERED")
        system.SetDemandValue("Hunger", 91)
        self.assertEqual(system.GetDemandLevelValue("Hunger")["level"], "OVERFLOW")

    def test_get_demand_level_value_supports_energy_deficit(self):
        """Energy 应按高充电需求值计算等级。"""
        system = MarsdogNeedSystem()

        system.SetDemandValue("Energy", 80)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "NORMAL")
        system.SetDemandValue("Energy", 81)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "TRIGGERED")
        system.SetDemandValue("Energy", 90)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "TRIGGERED")
        system.SetDemandValue("Energy", 91)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "OVERFLOW")

    def test_demand_signal_events_emit_only_on_level_change(self):
        """需求事件只应在等级变化时输出一次。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetDemandSignalEventsValue(timestamp=1.0), [])

        system.SetDemandValue("Hunger", 71)
        events = system.GetDemandSignalEventsValue(timestamp=2.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_TRIGGERED")
        self.assertEqual(events[0]["level"], "TRIGGERED")
        self.assertEqual(events[0]["previousLevel"], "NORMAL")
        self.assertEqual(system.GetDemandSignalEventsValue(timestamp=3.0), [])

        system.SetDemandValue("Hunger", 95)
        events = system.GetDemandSignalEventsValue(timestamp=4.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_OVERFLOW")
        self.assertEqual(events[0]["previousLevel"], "TRIGGERED")

        system.SetDemandValue("Hunger", 50)
        events = system.GetDemandSignalEventsValue(timestamp=5.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_RECOVERED")
        self.assertEqual(events[0]["previousLevel"], "OVERFLOW")


if __name__ == "__main__":
    unittest.main()
