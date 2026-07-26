import unittest

from marsdog_core import MarsdogNeedSystem
from marsdog_core.types import ActionResultType


class EnergyBehaviorTest(unittest.TestCase):
    def test_default_and_morning_energy_represent_full_battery(self):
        """默认和晨起 Energy 应为 0，对应满电 100%。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetDemandValue("Energy"), 0)
        self.assertEqual(system.GetBatteryValue(), 100)
        self.assertEqual(system.InitializeMorningEnergy(), 0)
        self.assertEqual(system.GetBatteryValue(), 100)

    def test_energy_is_battery_deficit(self):
        """Energy 应保存 100 减去硬件电量百分比。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.SetEnergyBatteryValue(35))

        self.assertEqual(system.GetBatteryValue(), 35)
        self.assertEqual(system.GetDemandValue("Energy"), 65)

    def test_battery_value_clamps_range_before_conversion(self):
        """电量写入也应限制在 0-100。"""
        system = MarsdogNeedSystem()

        system.SetEnergyBatteryValue(130)
        self.assertEqual(system.GetBatteryValue(), 100)
        self.assertEqual(system.GetDemandValue("Energy"), 0)
        system.SetEnergyBatteryValue(-10)
        self.assertEqual(system.GetBatteryValue(), 0)
        self.assertEqual(system.GetDemandValue("Energy"), 100)

    def test_recharge_completed_uses_default_target(self):
        """充电完成没有 metadata 时恢复到目标电量并清空需求。"""
        system = MarsdogNeedSystem()
        system.SetEnergyBatteryValue(5)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_RECHARGE", "result_type": "COMPLETED"}))

        self.assertEqual(system.GetDemandValue("Energy"), 0)
        self.assertEqual(system.GetBatteryValue(), 100)

    def test_recharge_completed_honors_battery_metadata_aliases(self):
        """充电完成应转换三个兼容字段中的回传电量。"""
        for metadataKey in ("energyValue", "energy_value", "batteryValue"):
            system = MarsdogNeedSystem()
            system.SetEnergyBatteryValue(5)

            self.assertTrue(
                system.OnBehaviorResultEvent(
                    {
                        "action_type": "ACTION_RECHARGE",
                        "result_type": "COMPLETED",
                        "metadata": {metadataKey: 88},
                    }
                )
            )

            self.assertEqual(system.GetDemandValue("Energy"), 12)
            self.assertEqual(system.GetBatteryValue(), 88)

    def test_execute_recharge_clears_triggered_energy_need(self):
        """直接充电应解除触发状态并结算满足情绪。"""
        system = MarsdogNeedSystem()
        system.SetEnergyBatteryValue(5)
        appliedResults = []
        system.ApplyActionResultEmotion = (
            lambda resultType: appliedResults.append(resultType) or True
        )

        self.assertTrue(system.IsDemandUrgent("Energy"))
        self.assertTrue(system.ExecuteRecharge())

        self.assertEqual(system.GetDemandValue("Energy"), 0)
        self.assertFalse(system.IsDemandUrgent("Energy"))
        self.assertEqual(
            appliedResults,
            [ActionResultType.DEMAND_SATISFIED],
        )

    def test_recharge_interrupted_reduces_energy_once(self):
        """充电被打断应按全局规则单次 -20。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Energy", 50)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_RECHARGE", "result_type": "INTERRUPTED"}))

        self.assertEqual(system.GetDemandValue("Energy"), 30)


if __name__ == "__main__":
    unittest.main()
