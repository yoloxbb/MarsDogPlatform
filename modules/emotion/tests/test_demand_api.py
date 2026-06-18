import unittest

from marsdog_core import MarsdogBehaviorSystem


class DemandAPITest(unittest.TestCase):
    def test_set_demand_value_clamps_range(self):
        """需求写入时应限制在 0-100。"""
        system = MarsdogBehaviorSystem()

        self.assertTrue(system.SetDemandValue("Hunger", 150))
        self.assertEqual(system.GetDemandValue("Hunger"), 100)

        self.assertTrue(system.SetDemandValue("Hunger", -10))
        self.assertEqual(system.GetDemandValue("Hunger"), 0)

    def test_invalid_demand_returns_false(self):
        """非法需求名应返回失败。"""
        system = MarsdogBehaviorSystem()

        self.assertFalse(system.SetDemandValue("UnknownDemand", 50))

    def test_is_demand_urgent_uses_config_threshold(self):
        """需求紧急判断应读取配置阈值。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 71)
        system.SetDemandValue("Cleanliness", 71)

        self.assertTrue(system.IsDemandUrgent("Hunger"))
        self.assertTrue(system.IsDemandUrgent("Cleanliness"))

    def test_get_most_urgent_demand_uses_raw_value(self):
        """同层需求比较不换算紧迫度，直接按原始值排序。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Bladder", 86)

        self.assertEqual(system.GetMostUrgentDemand(), "Bladder")


if __name__ == "__main__":
    unittest.main()
