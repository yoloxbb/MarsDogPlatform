import random
import unittest
from datetime import datetime, timedelta, timezone

from marsdog_core import (
    MarsdogEmotionSystem,
    MarsdogNeedSystem,
    MarsdogTimeController,
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
        timeMode: str,
        startTime: str = "06:00",
    ) -> tuple[MarsdogTimeController, MutableClock]:
        """创建具有固定本地日期的可控虚拟时钟。"""
        wallDateTime = datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc)
        clock = MutableClock(wallDateTime.timestamp())
        controller = MarsdogTimeController(
            timeMode,
            startTime,
            wallTimeProvider=clock.GetWallTimeValue,
            monotonicProvider=clock.GetMonotonicValue,
        )
        return controller, clock

    def test_time_modes_scale_virtual_elapsed_time(self):
        """三种模式应按 1、2、12 倍推进虚拟时间。"""
        for mode, scale in (("standard_24h", 1), ("demo_12h", 2), ("demo_2h", 12)):
            controller, clock = self._CreateController(mode)

            clock.Advance(600.0)

            elapsed = (
                controller.GetVirtualDateTimeValue()
                - controller.GetVirtualStartDateTimeValue()
            ).total_seconds()
            self.assertEqual(controller.GetTimeScaleValue(), scale)
            self.assertEqual(elapsed, 600.0 * scale)
            self.assertEqual(controller.GetRealIntervalValue(600.0), 600.0 / scale)

    def test_auto_start_rules(self):
        """标准模式跟随真实时间，压缩模式默认从本地 06:00 开始。"""
        standard, _ = self._CreateController("standard_24h", "auto")
        accelerated, _ = self._CreateController("demo_2h", "auto")

        expectedWallTime = datetime.fromtimestamp(
            datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc).timestamp()
        ).astimezone()
        self.assertEqual(standard.GetVirtualStartDateTimeValue(), expectedWallTime)
        self.assertEqual(accelerated.GetVirtualStartDateTimeValue().hour, 6)
        self.assertEqual(accelerated.GetVirtualStartDateTimeValue().minute, 0)

    def test_explicit_start_time_overrides_default(self):
        """HH:MM 参数应覆盖默认虚拟起始时间。"""
        controller, _ = self._CreateController("demo_2h", "18:25")

        start = controller.GetVirtualStartDateTimeValue()

        self.assertEqual((start.hour, start.minute, start.second), (18, 25, 0))

    def test_invalid_time_configuration_is_rejected(self):
        """非法模式和非法 HH:MM 应直接拒绝。"""
        with self.assertRaises(ValueError):
            self._CreateController("demo_3h")
        with self.assertRaises(ValueError):
            self._CreateController("demo_2h", "24:00")
        with self.assertRaises(ValueError):
            self._CreateController("demo_2h", "6:00")

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

    def test_time_context_keeps_wall_timestamp_and_reports_virtual_time(self):
        """timeContext 应保留顶层真实时间并报告虚拟时间信息。"""
        controller, clock = self._CreateController("demo_2h")
        clock.Advance(120.0)
        payload = {"timestamp": 1234.5, "value": 10}

        result = GetMessageWithTimeContextValue(payload, controller)

        self.assertEqual(result["timestamp"], 1234.5)
        self.assertEqual(result["timeContext"]["wallTimestamp"], 1234.5)
        self.assertEqual(result["timeContext"]["mode"], "demo_2h")
        self.assertEqual(result["timeContext"]["scale"], 12)
        self.assertEqual(result["timeContext"]["virtualElapsedSeconds"], 1440.0)

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

    def test_need_trajectory_is_equal_for_all_time_modes(self):
        """相同虚拟 Tick 序列在三种模式下应得到相同需求轨迹。"""
        allTrajectories = []
        for mode in ("standard_24h", "demo_12h", "demo_2h"):
            controller, clock = self._CreateController(mode)
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

    def test_emotion_decay_and_level_events_are_equal_for_all_time_modes(self):
        """相同虚拟秒数应得到相同情绪值和完整区间事件轨迹。"""
        allResults = []
        for mode in ("standard_24h", "demo_12h", "demo_2h"):
            controller, clock = self._CreateController(mode)
            scheduler = VirtualTickScheduler(
                controller.GetVirtualStartDateTimeValue(),
                1.0,
            )
            system = MarsdogEmotionSystem(randomGenerator=random.Random(2026))
            system.SetEmotionValue("Joy", 90)
            system.GetEmotionSignalEventsValue()
            eventTypes = []

            for _ in range(30):
                clock.Advance(controller.GetRealIntervalValue(1.0))
                dueTicks = scheduler.GetDueTickDateTimesValue(
                    controller.GetVirtualDateTimeValue()
                )
                self.assertEqual(len(dueTicks), 1)
                system.ApplyEmotionDecay(1.0)
                eventTypes.extend(
                    event["event_type"]
                    for event in system.GetEmotionSignalEventsValue()
                )
            allResults.append((system.GetAllEmotions(), eventTypes))

        self.assertEqual(allResults[0], allResults[1])
        self.assertEqual(allResults[1], allResults[2])
        self.assertIn("EMO_JOY_MID", allResults[0][1])
        self.assertIn("EMO_JOY_LOW", allResults[0][1])


if __name__ == "__main__":
    unittest.main()
