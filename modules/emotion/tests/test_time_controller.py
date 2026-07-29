import random
import unittest
from datetime import datetime, timedelta, timezone

from marsdog_core import (
    MarsdogEmotionSystem,
    MarsdogNeedSystem,
    MarsdogTimeController,
    RealTimeTickScheduler,
    VirtualTickScheduler,
)
from marsdog_ros2.time_context import GetMessageWithTimeContextValue, GetRandomGeneratorValue


class MutableClock:
    """为虚拟时钟测试提供可控的墙上时间和单调时间。"""

    def __init__(self, wallTimestamp: float, monotonicValue: float = 100.0) -> None:
        """初始化两个测试时钟。"""
        self.wallTimestamp = wallTimestamp
        self.monotonicValue = monotonicValue

    def GetWallTimeValue(self) -> float:
        """获取测试墙上时间。"""
        return self.wallTimestamp

    def GetMonotonicValue(self) -> float:
        """获取测试单调时间。"""
        return self.monotonicValue

    def Advance(self, realSeconds: float) -> None:
        """同步推进测试墙上时间和单调时间。"""
        self.wallTimestamp += realSeconds
        self.monotonicValue += realSeconds


class TimeControllerTest(unittest.TestCase):
    def _CreateController(
        self,
        timeScale: int,
        startTime: str = "06:00",
    ) -> tuple[MarsdogTimeController, MutableClock]:
        """创建具有固定本地日期的可控虚拟时钟。"""
        wallDateTime = datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc)
        clock = MutableClock(wallDateTime.timestamp())
        controller = MarsdogTimeController(
            timeScale,
            startTime,
            wallTimeProvider=clock.GetWallTimeValue,
            monotonicProvider=clock.GetMonotonicValue,
        )
        return controller, clock

    def test_integer_scales_advance_virtual_time(self):
        """常用整数倍率应正确推进虚拟时间并换算真实间隔。"""
        for scale in (1, 2, 3, 7, 12, 24, 50, 100):
            controller, clock = self._CreateController(scale)

            clock.Advance(600.0)

            elapsed = (
                controller.GetVirtualDateTimeValue()
                - controller.GetVirtualStartDateTimeValue()
            ).total_seconds()
            self.assertEqual(controller.GetTimeScaleValue(), scale)
            self.assertEqual(elapsed, 600.0 * scale)
            self.assertEqual(controller.GetRealIntervalValue(600.0), 600.0 / scale)

    def test_all_supported_integer_scales_are_accepted(self):
        """1-100 的每个整数倍率都应可以创建时间控制器。"""
        for scale in range(1, 101):
            controller, _ = self._CreateController(scale)

            self.assertEqual(controller.GetTimeScaleValue(), scale)

    def test_runtime_scale_switch_keeps_virtual_time_continuous(self):
        """运行时执行 1→100→7 不得重置或跳变虚拟时间。"""
        controller, clock = self._CreateController(1)
        clock.Advance(100.0)
        beforeFirstSwitch = controller.GetVirtualDateTimeValue()

        self.assertTrue(controller.SetTimeScaleValue(100))
        afterFirstSwitch = controller.GetVirtualDateTimeValue()

        self.assertEqual(afterFirstSwitch, beforeFirstSwitch)
        self.assertEqual(controller.GetTimeScaleValue(), 100)
        self.assertEqual(controller.GetTimeRevisionValue(), 1)

        clock.Advance(10.0)
        self.assertEqual(
            (
                controller.GetVirtualDateTimeValue() - beforeFirstSwitch
            ).total_seconds(),
            1000.0,
        )

        beforeSecondSwitch = controller.GetVirtualDateTimeValue()
        self.assertTrue(controller.SetTimeScaleValue(7))
        self.assertEqual(controller.GetVirtualDateTimeValue(), beforeSecondSwitch)
        self.assertEqual(controller.GetTimeScaleValue(), 7)
        self.assertEqual(controller.GetTimeRevisionValue(), 2)

        clock.Advance(10.0)
        self.assertEqual(
            (
                controller.GetVirtualDateTimeValue() - beforeSecondSwitch
            ).total_seconds(),
            70.0,
        )

    def test_repeated_scale_switch_preserves_original_elapsed_time(self):
        """多次切换后 virtualElapsedSeconds 仍从原虚拟起点累计。"""
        controller, clock = self._CreateController(1)
        clock.Advance(60.0)
        controller.SetTimeScaleValue(2)
        clock.Advance(30.0)
        controller.SetTimeScaleValue(12)
        clock.Advance(5.0)

        context = controller.GetTimeContextValue()

        self.assertEqual(context["revision"], 2)
        self.assertEqual(context["virtualElapsedSeconds"], 180.0)

    def test_setting_same_scale_does_not_increment_revision(self):
        """重复设置当前倍率不应增加修订号。"""
        controller, _ = self._CreateController(7)

        self.assertTrue(controller.SetTimeScaleValue(7))
        self.assertEqual(controller.GetTimeRevisionValue(), 0)

    def test_virtual_time_can_anchor_at_accelerated_midnight_steps(self):
        """凌晨离散步骤结束后应恢复各自的基础倍率。"""
        for scale in (1, 7, 24, 100):
            controller, clock = self._CreateController(scale, "00:00")
            start = controller.GetVirtualStartDateTimeValue()

            for stepSequence in range(1, 37):
                controller.SetVirtualDateTimeValue(
                    start + timedelta(minutes=10 * stepSequence)
                )

            self.assertEqual(
                controller.GetVirtualDateTimeValue(),
                start + timedelta(hours=6),
            )
            self.assertEqual(controller.GetTimeRevisionValue(), 0)

            clock.Advance(1.0)
            self.assertEqual(
                controller.GetVirtualDateTimeValue(),
                start + timedelta(hours=6, seconds=scale),
            )

    def test_virtual_time_anchor_rejects_time_before_start(self):
        """离散时间锚点不得早于本次虚拟起点。"""
        controller, _ = self._CreateController(24, "00:00")

        with self.assertRaises(ValueError):
            controller.SetVirtualDateTimeValue(
                controller.GetVirtualStartDateTimeValue()
                - timedelta(seconds=1)
            )

    def test_remote_time_context_synchronizes_scale_and_anchor(self):
        """计算节点应只按权威 scale 和时间字段对齐本地时钟。"""
        source, sourceClock = self._CreateController(1)
        sourceClock.Advance(20.0)
        source.SetTimeScaleValue(7)
        sourceClock.Advance(5.0)
        sourceContext = source.GetTimeContextValue()
        sourceContext["mode"] = "ignored_legacy_label"

        target, _ = self._CreateController(2, "18:00")
        self.assertTrue(target.SetTimeContextValue(sourceContext))

        self.assertEqual(target.GetTimeScaleValue(), 7)
        self.assertEqual(target.GetTimeRevisionValue(), 1)
        self.assertEqual(
            target.GetVirtualDateTimeValue().isoformat(),
            sourceContext["virtualDateTime"],
        )

    def test_remote_time_context_preserves_acceleration_metadata(self):
        """计算节点应在状态输出中保留凌晨有效倍率上下文。"""
        source, _ = self._CreateController(24, "00:00")
        target, _ = self._CreateController(24, "00:00")
        context = source.GetTimeContextValue()
        context["effectiveScale"] = 720.0
        context["midnightAcceleration"] = {
            "enabled": True,
            "active": True,
            "durationSeconds": 30.0,
        }

        self.assertTrue(target.SetTimeContextValue(context))

        synchronizedContext = target.GetTimeContextValue()
        self.assertEqual(synchronizedContext["scale"], 24)
        self.assertEqual(synchronizedContext["effectiveScale"], 720.0)
        self.assertTrue(
            synchronizedContext["midnightAcceleration"]["active"]
        )

    def test_invalid_acceleration_context_is_rejected(self):
        """有效倍率和凌晨加速上下文字段必须使用合法类型。"""
        source, _ = self._CreateController(24, "00:00")
        target, _ = self._CreateController(24, "00:00")

        for invalidScale in (0, -1, True, "720"):
            context = source.GetTimeContextValue()
            context["effectiveScale"] = invalidScale
            with self.assertRaises(ValueError):
                target.SetTimeContextValue(context)

        context = source.GetTimeContextValue()
        context["midnightAcceleration"] = True
        with self.assertRaises(ValueError):
            target.SetTimeContextValue(context)

    def test_auto_start_rules(self):
        """1 倍跟随真实时间，2-100 倍默认从本地 06:00 开始。"""
        standard, _ = self._CreateController(1, "auto")

        expectedWallTime = datetime.fromtimestamp(
            datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc).timestamp()
        ).astimezone()
        self.assertEqual(standard.GetVirtualStartDateTimeValue(), expectedWallTime)
        for scale in range(2, 101):
            accelerated, _ = self._CreateController(scale, "auto")
            self.assertEqual(accelerated.GetVirtualStartDateTimeValue().hour, 6)
            self.assertEqual(accelerated.GetVirtualStartDateTimeValue().minute, 0)

    def test_explicit_start_time_overrides_default(self):
        """HH:MM 参数应覆盖默认虚拟起始时间。"""
        controller, _ = self._CreateController(7, "18:25")

        start = controller.GetVirtualStartDateTimeValue()

        self.assertEqual((start.hour, start.minute, start.second), (18, 25, 0))

    def test_invalid_time_configuration_is_rejected(self):
        """非法倍率类型、越界倍率和非法 HH:MM 应直接拒绝。"""
        for invalidScale in (
            0,
            101,
            -1,
            True,
            False,
            1.0,
            7.5,
            "1",
            "demo_2h",
            None,
        ):
            with self.assertRaises(ValueError):
                self._CreateController(invalidScale)
        with self.assertRaises(ValueError):
            self._CreateController(7, "24:00")
        with self.assertRaises(ValueError):
            self._CreateController(7, "6:00")

    def test_invalid_time_context_scale_is_rejected(self):
        """权威时间上下文中的倍率也必须是 1-100 整数。"""
        source, _ = self._CreateController(7)
        target, _ = self._CreateController(1)

        for invalidScale in (0, 101, True, 7.0, "7"):
            context = source.GetTimeContextValue()
            context["scale"] = invalidScale
            with self.assertRaises(ValueError):
                target.SetTimeContextValue(context)

    def test_scheduler_catches_up_every_missed_tick(self):
        """定时器延迟时应逐个返回遗漏 Tick，不做合并。"""
        start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
        scheduler = VirtualTickScheduler(start, 10.0)

        dueTicks = scheduler.GetDueTickDateTimesValue(start + timedelta(seconds=35))

        self.assertEqual(
            dueTicks,
            [
                start + timedelta(seconds=10),
                start + timedelta(seconds=20),
                start + timedelta(seconds=30),
            ],
        )
        self.assertEqual(
            scheduler.GetNextTickDateTimeValue(),
            start + timedelta(seconds=40),
        )

    def test_scheduler_can_align_without_replaying_full_history(self):
        """首次晚到同步可对齐当前边界，并只消费当前 Tick。"""
        start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
        scheduler = VirtualTickScheduler(start, 10.0)
        current = start + timedelta(seconds=120)

        scheduler.AlignToDateTimeValue(current, includeCurrent=True)

        self.assertEqual(scheduler.GetDueTickDateTimesValue(current), [current])
        self.assertEqual(
            scheduler.GetNextTickDateTimeValue(),
            current + timedelta(seconds=10),
        )

    def test_real_time_scheduler_catches_up_delayed_ticks(self):
        """真实时间调度器延迟后应补算全部完整秒 Tick。"""
        scheduler = RealTimeTickScheduler(100.0, 1.0)

        self.assertEqual(scheduler.GetDueTickCountValue(100.9), 0)
        self.assertEqual(scheduler.GetDueTickCountValue(105.2), 5)
        self.assertEqual(scheduler.GetNextTickSecondsValue(), 106.0)
        self.assertEqual(scheduler.GetDueTickCountValue(108.9), 3)
        self.assertEqual(scheduler.GetNextTickSecondsValue(), 109.0)

    def test_real_time_scheduler_rejects_invalid_values(self):
        """真实时间调度器应拒绝非法起点、间隔和当前时间。"""
        for invalidStart in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                RealTimeTickScheduler(invalidStart)
        for invalidInterval in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                RealTimeTickScheduler(100.0, invalidInterval)

        scheduler = RealTimeTickScheduler(100.0)
        with self.assertRaises(ValueError):
            scheduler.GetDueTickCountValue(float("nan"))

    def test_time_context_keeps_wall_timestamp_and_reports_virtual_time(self):
        """timeContext 应保留顶层真实时间并报告虚拟时间信息。"""
        controller, clock = self._CreateController(7)
        clock.Advance(120.0)
        payload = {"timestamp": 1234.5, "value": 10}

        result = GetMessageWithTimeContextValue(payload, controller)

        self.assertEqual(result["timestamp"], 1234.5)
        self.assertEqual(result["timeContext"]["wallTimestamp"], 1234.5)
        self.assertEqual(result["timeContext"]["mode"], "custom")
        self.assertEqual(result["timeContext"]["scale"], 7)
        self.assertEqual(result["timeContext"]["virtualElapsedSeconds"], 840.0)

    def test_legacy_mode_labels_are_output_only(self):
        """1、2、12 倍保留旧标签，其他倍率统一输出 custom。"""
        expectedLabels = {
            1: "standard_24h",
            2: "demo_12h",
            7: "custom",
            12: "demo_2h",
            24: "custom",
            100: "custom",
        }
        for scale, label in expectedLabels.items():
            controller, _ = self._CreateController(scale)

            self.assertEqual(controller.GetTimeContextValue()["mode"], label)

    def test_random_seed_validation_and_reproducibility(self):
        """固定种子应可复现，-1 保持随机，其他值拒绝。"""
        first = GetRandomGeneratorValue(12345)
        second = GetRandomGeneratorValue("12345")

        self.assertIsInstance(first, random.Random)
        self.assertEqual(first.randint(0, 1000), second.randint(0, 1000))
        self.assertIsNone(GetRandomGeneratorValue(-1))
        for invalidSeed in (-2, 1.5, True, "1.5", "abc"):
            with self.assertRaises(ValueError):
                GetRandomGeneratorValue(invalidSeed)

    def test_need_trajectory_is_equal_for_selected_time_scales(self):
        """相同虚拟 Tick 序列在 1、7、24、100 倍下应得到相同需求轨迹。"""
        allTrajectories = []
        for scale in (1, 7, 24, 100):
            controller, clock = self._CreateController(scale)
            scheduler = VirtualTickScheduler(
                controller.GetVirtualStartDateTimeValue(),
                600.0,
            )
            system = MarsdogNeedSystem(randomGenerator=random.Random(2026))
            system.ResetDemandsToMorningInitialValues(
                controller.GetVirtualStartDateTimeValue()
            )
            trajectory = []

            for _ in range(144):
                clock.Advance(controller.GetRealIntervalValue(600.0))
                dueTicks = scheduler.GetDueTickDateTimesValue(
                    controller.GetVirtualDateTimeValue()
                )
                self.assertEqual(len(dueTicks), 1)
                system.UpdateNaturalDemandsByTime(dueTicks[0])
                if not system.IsSleeping() and system.IsSleepActionAllowed(dueTicks[0]):
                    system.ExecuteSleep()
                trajectory.append(
                    (
                        system.GetAllDemands(),
                        system.IsSleeping(),
                        system.GetSleepDepthValue(),
                    )
                )
            allTrajectories.append(trajectory)

        self.assertEqual(allTrajectories[0], allTrajectories[1])
        self.assertEqual(allTrajectories[1], allTrajectories[2])
        self.assertEqual(allTrajectories[2], allTrajectories[3])

    def test_battery_endurance_uses_scaled_virtual_time(self):
        """两虚拟小时续航应按倍率换算为对应真实耗时。"""
        for scale in (1, 7, 24, 100):
            controller, clock = self._CreateController(scale)
            scheduler = VirtualTickScheduler(
                controller.GetVirtualStartDateTimeValue(),
                600.0,
            )
            system = MarsdogNeedSystem()

            # 两虚拟小时在真实世界中应只消耗 7200 / scale 秒。
            clock.Advance(7200.0 / scale)
            dueTicks = scheduler.GetDueTickDateTimesValue(
                controller.GetVirtualDateTimeValue()
            )
            for tickDateTime in dueTicks:
                system.UpdateNaturalDemandsByTime(tickDateTime)

            self.assertEqual(len(dueTicks), 12)
            self.assertEqual(system.GetBatteryValue(), 0)

    def test_emotion_decay_is_equal_for_same_real_time_across_scales(self):
        """相同真实时间下各倍率应得到一致衰减且不发布恢复事件。"""
        allResults = []
        for scale in (1, 7, 24, 100):
            controller, clock = self._CreateController(scale)
            scheduler = RealTimeTickScheduler(
                clock.GetMonotonicValue(),
                1.0,
            )
            system = MarsdogEmotionSystem(randomGenerator=random.Random(2026))
            system.SetEmotionValue("Joy", 90)
            system.GetEmotionSignalEventsValue()
            eventTypes = []

            for _ in range(30 * scale):
                clock.Advance(controller.GetRealIntervalValue(1.0))
                dueTickCount = scheduler.GetDueTickCountValue(
                    clock.GetMonotonicValue()
                )
                for _ in range(dueTickCount):
                    system.ApplyEmotionDecay(1.0)
                    eventTypes.extend(
                        event["event_type"]
                        for event in system.GetEmotionSignalEventsValue()
                    )
            allResults.append((system.GetAllEmotions(), eventTypes))

        self.assertEqual(allResults[0], allResults[1])
        self.assertEqual(allResults[1], allResults[2])
        self.assertEqual(allResults[2], allResults[3])
        self.assertEqual(allResults[0][1], [])

    def test_same_virtual_duration_decays_by_real_duration(self):
        """相同虚拟时长在高倍率下应因真实耗时更短而衰减更少。"""
        joyValues = []
        for scale in (1, 7, 24, 100):
            controller, clock = self._CreateController(scale)
            scheduler = RealTimeTickScheduler(clock.GetMonotonicValue(), 1.0)
            system = MarsdogEmotionSystem(randomGenerator=random.Random(2026))
            system.SetEmotionValue("Joy", 90)

            clock.Advance(controller.GetRealIntervalValue(24.0))
            for _ in range(
                scheduler.GetDueTickCountValue(clock.GetMonotonicValue())
            ):
                system.ApplyEmotionDecay(1.0)
            joyValues.append(system.GetEmotionValue("Joy"))

        self.assertEqual(joyValues, [42, 84, 88, 90])

    def test_scale_switch_does_not_trigger_extra_emotion_decay(self):
        """倍率切换本身不应产生额外真实时间衰减 Tick。"""
        controller, clock = self._CreateController(1)
        scheduler = RealTimeTickScheduler(clock.GetMonotonicValue(), 1.0)

        clock.Advance(1.0)
        self.assertEqual(
            scheduler.GetDueTickCountValue(clock.GetMonotonicValue()),
            1,
        )
        controller.SetTimeScaleValue(100)
        self.assertEqual(
            scheduler.GetDueTickCountValue(clock.GetMonotonicValue()),
            0,
        )
        clock.Advance(0.5)
        controller.SetTimeScaleValue(7)
        self.assertEqual(
            scheduler.GetDueTickCountValue(clock.GetMonotonicValue()),
            0,
        )
        clock.Advance(0.5)
        self.assertEqual(
            scheduler.GetDueTickCountValue(clock.GetMonotonicValue()),
            1,
        )


if __name__ == "__main__":
    unittest.main()
