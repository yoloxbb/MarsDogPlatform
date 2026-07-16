import random
import unittest
from datetime import datetime, timedelta

from marsdog_core import MarsdogNeedSystem


class SleepinessBehaviorTest(unittest.TestCase):
    def test_initialize_morning_sleepiness_uses_range(self):
        """困倦晨起值应在 10-15 随机范围内。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningSleepiness()

        self.assertTrue(10 <= value <= 15)
        self.assertEqual(system.GetDemandValue("Sleepiness"), value)

    def test_sleepiness_time_growth_and_forced_value(self):
        """清醒时白天 +4，夜晚 +5，凌晨强制 90。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.UpdateSleepinessByTime(8)
        self.assertEqual(system.GetDemandValue("Sleepiness"), 14)
        system.UpdateSleepinessByTime(22)
        self.assertEqual(system.GetDemandValue("Sleepiness"), 19)
        system.UpdateSleepinessByTime(2)
        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)

    def test_lights_off_forces_sleepiness_to_90(self):
        """关灯会让清醒状态下 Sleepiness 直接变成 90。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 20)

        system.SetLightsOffValue(True)
        system.UpdateSleepinessByTime(12)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)

    def test_sleep_action_allowed_rules(self):
        """睡眠触发需满足阈值和可入睡时段。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 80)

        self.assertFalse(system.IsSleepActionAllowed(7))
        self.assertTrue(system.IsSleepActionAllowed(12))
        self.assertTrue(system.IsSleepActionAllowed(22))
        self.assertTrue(system.IsSleepActionAllowed(2))

    def test_execute_sleep_enters_shallow_sleep(self):
        """ACTION_SLEEP STARTED 应进入浅睡状态。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 80)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_SLEEP", "result_type": "STARTED"}))

        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetSleepDepthValue(), "Shallow")
        self.assertEqual(system.state.shallowSleepTicksRemaining, 14)

    def test_shallow_sleep_wakes_if_below_threshold_after_configured_ticks(self):
        """持续睡眠 14 Tick 后若不再超过阈值则自然醒来。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 68)
        system.ExecuteSleep()

        for _ in range(14):
            system.ApplySleepRecovery(12)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 40)
        self.assertFalse(system.IsSleeping())

    def test_shallow_sleep_turns_to_deep_if_still_tired(self):
        """浅睡结束仍超过阈值时转入深睡。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 100)
        system.ExecuteSleep()

        for _ in range(14):
            system.ApplySleepRecovery(12)

        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetSleepDepthValue(), "Deep")
        self.assertEqual(system.GetDemandValue("Sleepiness"), 72)

    def test_daily_awake_duration_matches_configured_target(self):
        """即时响应睡眠信号时，每日清醒时间应约为 6.5-7 小时。"""
        for initialValue in range(10, 16):
            system = MarsdogNeedSystem()
            system.SetDemandValue("Sleepiness", initialValue)
            currentTime = datetime(2026, 7, 16, 6, 0)
            awakeMinutes = 0
            sleepSessionCount = 0

            for _ in range(24 * 6):
                # 当前状态覆盖接下来的 10 分钟，再在 Tick 边界更新需求。
                if not system.IsSleeping():
                    awakeMinutes += 10
                currentTime += timedelta(minutes=10)
                system.UpdateSleepinessByTime(currentTime)
                if not system.IsSleeping() and system.IsSleepActionAllowed(currentTime):
                    system.ExecuteSleep()
                    sleepSessionCount += 1

            self.assertGreaterEqual(awakeMinutes, 390)
            self.assertLessEqual(awakeMinutes, 420)
            self.assertEqual(sleepSessionCount, 5)

    def test_deep_sleep_recovers_until_wakeup_threshold(self):
        """深睡每 Tick -15，低于醒来阈值后自然醒来。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 35)
        system.ExecuteSleep()
        system.state.sleepDepth = "Deep"

        system.ApplySleepRecovery(12)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 20)
        self.assertFalse(system.IsSleeping())

    def test_deep_sleep_does_not_wake_during_midnight_forced_sleep(self):
        """凌晨强制睡眠期间即使低于阈值也不自然醒。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Sleepiness", 25)
        system.ExecuteSleep()
        system.state.sleepDepth = "Deep"

        system.ApplySleepRecovery(2)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 10)
        self.assertTrue(system.IsSleeping())


if __name__ == "__main__":
    unittest.main()
