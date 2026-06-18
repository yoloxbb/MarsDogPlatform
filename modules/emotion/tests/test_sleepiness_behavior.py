import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class SleepinessBehaviorTest(unittest.TestCase):
    def test_initialize_morning_sleepiness_uses_random_range(self):
        """晨起困倦值应落在 10-15。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningSleepiness()

        self.assertGreaterEqual(value, 10)
        self.assertLessEqual(value, 15)
        self.assertEqual(system.GetDemandValue("Sleepiness"), value)

    def test_daytime_tick_increases_sleepiness_by_three(self):
        """白天每 10 分钟 Tick 应让 Sleepiness 增加 3。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.UpdateNaturalDemandsByTime(currentTime=8)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 13)

    def test_evening_tick_increases_sleepiness_by_five(self):
        """夜晚每 10 分钟 Tick 应让 Sleepiness 增加 5。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.UpdateNaturalDemandsByTime(currentTime=22)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 15)

    def test_midnight_awake_forces_sleepiness_to_ninety(self):
        """凌晨清醒时应强制 Sleepiness 为 90。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.UpdateNaturalDemandsByTime(currentTime=2)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)

    def test_lights_off_forces_sleepiness_to_ninety(self):
        """识别到关灯时应强制 Sleepiness 为 90。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)
        system.SetLightsOffValue(True)

        system.UpdateNaturalDemandsByTime(currentTime=20)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)

    def test_sleepiness_over_65_triggers_sleep_action_in_daytime(self):
        """白天且非强制清醒时，Sleepiness 大于 65 应触发睡眠行为。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 66)

        system.Tick(currentTime=9)

        self.assertEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_sleepiness_over_65_does_not_trigger_sleep_in_evening_without_lights_off(self):
        """夜晚 21:00-00:00 未关灯时不直接触发睡眠。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 66)

        system.Tick(currentTime=22)

        self.assertNotEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_forced_awake_period_blocks_sleep_action(self):
        """强制清醒时段内不触发睡眠行为。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 80)

        system.Tick(currentTime=7)

        self.assertNotEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_midnight_forces_sleep_action(self):
        """凌晨应强制 Sleepiness 为 90 并触发睡眠行为。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)

        system.Tick(currentTime=2)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)
        self.assertEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_lights_off_forces_sleep_action(self):
        """关灯后即使不在白天也应触发睡眠行为。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)
        system.SetLightsOffValue(True)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)
        self.assertEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_execute_sleep_sets_shallow_depth(self):
        """执行睡眠行为后先进入浅睡。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 80)

        self.assertTrue(system.ExecuteSleep())

        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetSleepDepthValue(), "Shallow")
        self.assertEqual(system.state.shallowSleepTicksRemaining, 3)

    def test_execute_sleep_still_starts_with_shallow_when_sleepiness_is_high(self):
        """Sleepiness 很高时也先进入浅睡，再由状态机转深睡。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 95)

        self.assertTrue(system.ExecuteSleep())

        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetSleepDepthValue(), "Shallow")

    def test_shallow_sleep_recovery_decreases_by_two(self):
        """浅睡每 10 分钟恢复 2 点困倦。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 80)
        system.ExecuteSleep()

        system.ApplySleepRecovery()

        self.assertEqual(system.GetDemandValue("Sleepiness"), 78)
        self.assertEqual(system.state.sleepDurationMinutes, 10)
        self.assertEqual(system.state.shallowSleepTicksRemaining, 2)

    def test_shallow_sleep_turns_to_deep_after_three_ticks_when_still_tired(self):
        """浅睡 3 个 Tick 后，若仍大于 65 则进入深睡。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 80)
        system.ExecuteSleep()

        for _ in range(3):
            system.ApplySleepRecovery(currentTime=9)

        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetDemandValue("Sleepiness"), 74)
        self.assertEqual(system.GetSleepDepthValue(), "Deep")

    def test_shallow_sleep_wakes_after_three_ticks_when_no_longer_tired(self):
        """浅睡 3 个 Tick 后，若不再大于 65 则自然醒来。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 68)
        system.ExecuteSleep()

        for _ in range(3):
            system.ApplySleepRecovery(currentTime=9)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 62)
        self.assertFalse(system.IsSleeping())

    def test_deep_sleep_recovery_decreases_by_fifteen(self):
        """深睡每 10 分钟恢复 15 点困倦。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 95)
        system.ExecuteSleep()
        system.state.sleepDepth = "Deep"

        system.ApplySleepRecovery()

        self.assertEqual(system.GetDemandValue("Sleepiness"), 80)
        self.assertEqual(system.state.sleepDurationMinutes, 10)

    def test_sleepiness_under_threshold_auto_wakes_up(self):
        """Sleepiness 恢复到 20 以下后应自动醒来。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 21)
        system.ExecuteSleep()
        system.state.sleepDepth = "Deep"

        system.ApplySleepRecovery(currentTime=9)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 6)
        self.assertFalse(system.IsSleeping())

    def test_midnight_deep_sleep_does_not_wake_even_under_threshold(self):
        """00:00-06:00 深睡低于醒来阈值也不会自然醒来。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 21)
        system.ExecuteSleep()
        system.state.sleepDepth = "Deep"

        system.ApplySleepRecovery(currentTime=2)

        self.assertEqual(system.GetDemandValue("Sleepiness"), 6)
        self.assertTrue(system.IsSleeping())

    def test_morning_reset_wakes_forced_sleep(self):
        """06:00 晨起重置后应退出凌晨强制睡眠。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Sleepiness", 80)
        system.ExecuteSleep()

        system.Tick(currentTime=2)
        self.assertTrue(system.IsSleeping())

        system.Tick(currentTime=6)

        self.assertFalse(system.IsSleeping())
        self.assertGreaterEqual(system.GetDemandValue("Sleepiness"), 10)
        self.assertLessEqual(system.GetDemandValue("Sleepiness"), 15)

    def test_sleep_behavior_tree_randomly_selects_one_action_per_phase(self):
        """ACTION_SLEEP 行为树每个阶段应只随机抽 1 个动作。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Sleepiness", 80)
        steps = system.GetActionSequence("ACTION_SLEEP")

        self.assertEqual(len(steps), 3)
        self.assertIn(
            steps[0],
            {
                "ACT_CIRCLE_AROUND",
                "ACT_SCRATCH_BED_OR_GROUND",
                "ACT_LIE_ON_SIDE_AND_STRETCH",
                "ACT_LICK_FUR_OR_PAWS",
            },
        )
        self.assertIn(
            steps[1],
            {
                "ACT_FLIP_BODY",
                "ACT_WHINE_SOFTLY",
                "ACT_TWITCH_OR_KICK_LEGS",
                "ACT_SHAKE_HEAD_OR_SMACK_LIPS",
                "ACT_WAG_TAIL",
                "ACT_YAWN",
            },
        )
        self.assertIn(
            steps[2],
            {
                "ACT_GETUP_CRAWL",
                "ACT_GETUP_ROLL",
                "ACT_GETUP_BOUNCE",
                "ACT_GETUP_STRETCH",
                "ACT_GETUP_SIT",
            },
        )

    def test_sleep_behavior_tree_success_enters_sleeping_state(self):
        """ACTION_SLEEP 行为树成功后应进入睡眠状态。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Sleepiness", 80)
        system.Tick(currentTime=9)

        finalStatus = ""
        for _ in range(20):
            finalStatus = system.TickCurrentBehaviorTree()
            currentAction = system.GetCurrentConcreteAction()
            if currentAction:
                system.MarkCurrentConcreteActionDone()
            if finalStatus == "SUCCESS":
                break

        self.assertEqual(finalStatus, "SUCCESS")
        self.assertTrue(system.IsSleeping())
        self.assertEqual(system.GetSleepDepthValue(), "Shallow")


if __name__ == "__main__":
    unittest.main()
