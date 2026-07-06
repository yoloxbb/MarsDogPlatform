import unittest

from marsdog_core import MarsdogNeedSystem


class EnergyBehaviorTest(unittest.TestCase):
    def test_energy_battery_value_is_demand_value(self):
        """Energy 当前就等于硬件电量百分比。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.SetEnergyBatteryValue(35))

        self.assertEqual(system.GetBatteryValue(), 35)
        self.assertEqual(system.GetDemandValue("Energy"), 35)

    def test_energy_value_clamps_range(self):
        """电量写入也应限制在 0-100。"""
        system = MarsdogNeedSystem()

        system.SetEnergyBatteryValue(130)
        self.assertEqual(system.GetBatteryValue(), 100)
        system.SetEnergyBatteryValue(-10)
        self.assertEqual(system.GetBatteryValue(), 0)

    def test_recharge_completed_uses_default_target(self):
        """充电完成没有 metadata 时恢复到配置目标。"""
        system = MarsdogNeedSystem()
        system.SetEnergyBatteryValue(5)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_RECHARGE", "result_type": "COMPLETED"}))

        self.assertEqual(system.GetDemandValue("Energy"), 100)

    def test_recharge_completed_honors_energy_metadata(self):
        """充电完成带 energyValue 时按回传电量写入。"""
        system = MarsdogNeedSystem()
        system.SetEnergyBatteryValue(5)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_RECHARGE",
                    "result_type": "COMPLETED",
                    "metadata": {"energyValue": 88},
                }
            )
        )

        self.assertEqual(system.GetDemandValue("Energy"), 88)

    def test_recharge_interrupted_reduces_energy_once(self):
        """充电被打断应按全局规则单次 -20。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Energy", 50)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_RECHARGE", "result_type": "INTERRUPTED"}))

        self.assertEqual(system.GetDemandValue("Energy"), 30)


if __name__ == "__main__":
    unittest.main()
