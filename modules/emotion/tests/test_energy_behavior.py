import unittest
from datetime import datetime, timedelta

from marsdog_core import MarsdogNeedSystem, VirtualTickScheduler
from marsdog_core.types import ActionResultType


class EnergyBehaviorTest(unittest.TestCase):
    def test_default_and_morning_energy_represent_full_battery(self):
        """默认和显式初始化 Energy 应为 0，对应满电 100%。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetDemandValue("Energy"), 0)
        self.assertEqual(system.GetBatteryValue(), 100)
        self.assertEqual(system.InitializeMorningEnergy(), 0)
        self.assertEqual(system.GetBatteryValue(), 100)

    def test_natural_drain_empties_full_battery_after_two_virtual_hours(self):
        """满电应在 12 个虚拟 10 分钟 Tick 后恰好耗尽。"""
        system = MarsdogNeedSystem()
        expectedEnergyValues = [8, 16, 25, 33, 41, 50, 58, 66, 75, 83, 91, 100]

        actualEnergyValues = [
            system.UpdateEnergyByTime()
            for _ in range(12)
        ]

        self.assertEqual(actualEnergyValues, expectedEnergyValues)
        self.assertEqual(system.GetBatteryValue(), 0)

    def test_midnight_acceleration_only_drains_for_thirty_real_seconds(self):
        """凌晨六小时压缩为30秒时，电池只按1倍累计30秒耗电。"""
        start = datetime(2026, 7, 29, 0, 0)
        scheduler = VirtualTickScheduler(start, 600.0)
        system = MarsdogNeedSystem()

        for tickDateTime in scheduler.GetDueTickDateTimesValue(
            start + timedelta(hours=6)
        ):
            system.UpdateNaturalDemandsByTime(
                tickDateTime,
                energyElapsedSeconds=30.0 / 36.0,
            )

        self.assertEqual(system.GetDemandValue("Energy"), 0)
        self.assertEqual(system.GetBatteryValue(), 100)
        self.assertAlmostEqual(system.state.energyDrainRemainder, 100.0 / 240.0)

        # 再累计42秒后总耗电时长为72秒，应下降1%。
        system.UpdateEnergyByTime(elapsedSeconds=42.0)
        self.assertEqual(system.GetBatteryValue(), 99)

    def test_morning_reset_does_not_refill_battery(self):
        """每日晨起需求重置不得把模拟电池重新充满。"""
        system = MarsdogNeedSystem()
        system.SetEnergyBatteryValue(40)

        system.ResetDemandsToMorningInitialValues(datetime(2026, 7, 29, 6, 0))

        self.assertEqual(system.GetDemandValue("Energy"), 60)
        self.assertEqual(system.GetBatteryValue(), 40)

    def test_recharge_clears_fractional_drain_progress(self):
        """充电完成后应从新的电量重新累计耗电小数余量。"""
        system = MarsdogNeedSystem()
        system.UpdateEnergyByTime()

        system.SetEnergyBatteryValue(100)
        system.UpdateEnergyByTime()
        system.UpdateEnergyByTime()

        self.assertEqual(system.GetDemandValue("Energy"), 16)
        self.assertEqual(system.GetBatteryValue(), 84)

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
