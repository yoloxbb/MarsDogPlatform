import unittest
from datetime import datetime, timezone

from marsdog_ros2.midnight_test_node import (
    SCENARIO_STEP_COUNT,
    BuildMidnightTestTimeStateValue,
    GetMidnightScenarioStartValue,
    GetMidnightScenarioStepDateTimeValue,
)


class MidnightScenarioTest(unittest.TestCase):
    def test_scenario_has_36_ten_minute_steps(self):
        """凌晨六小时场景应由36个虚拟10分钟步骤组成。"""
        start = datetime(2026, 7, 26, 14, 30, tzinfo=timezone.utc)

        virtualStart = GetMidnightScenarioStartValue(start)
        virtualEnd = GetMidnightScenarioStepDateTimeValue(
            virtualStart,
            SCENARIO_STEP_COUNT,
        )

        self.assertEqual((virtualStart.hour, virtualStart.minute), (0, 0))
        self.assertEqual((virtualEnd.hour, virtualEnd.minute), (6, 0))
        self.assertEqual(
            (virtualEnd - virtualStart).total_seconds(),
            6 * 60 * 60,
        )

    def test_time_state_uses_initialization_then_discrete_steps(self):
        """首条消息应初始化时间，后续消息应使用测试跳步事件。"""
        start = datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)

        initial = BuildMidnightTestTimeStateValue(start, 0, 30.0, 1000.0)
        firstStep = BuildMidnightTestTimeStateValue(start, 1, 30.0, 1001.0)
        finalStep = BuildMidnightTestTimeStateValue(
            start,
            SCENARIO_STEP_COUNT,
            30.0,
            1030.0,
        )

        self.assertEqual(initial["schema_version"], "1.0")
        self.assertEqual(initial["event_type"], "TIME_INITIALIZED")
        self.assertEqual(firstStep["event_type"], "TIME_TEST_STEP")
        self.assertEqual(firstStep["timeContext"]["scale"], 24)
        self.assertEqual(firstStep["testScenario"]["effectiveTimeScale"], 720)
        self.assertEqual(
            finalStep["timeContext"]["virtualDateTime"],
            "2026-07-26T06:00:00+00:00",
        )
        self.assertEqual(finalStep["timeContext"]["virtualElapsedSeconds"], 21600)

    def test_scenario_rejects_invalid_start_and_step(self):
        """场景构造应拒绝无时区起点和越界步骤。"""
        with self.assertRaises(ValueError):
            GetMidnightScenarioStartValue(datetime(2026, 7, 26, 14, 30))

        start = datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            GetMidnightScenarioStepDateTimeValue(
                datetime(2026, 7, 26, 0, 0),
                1,
            )
        for invalidStep in (-1, SCENARIO_STEP_COUNT + 1, True, 1.0):
            with self.assertRaises(ValueError):
                GetMidnightScenarioStepDateTimeValue(start, invalidStep)
        with self.assertRaises(ValueError):
            BuildMidnightTestTimeStateValue(start, 1, 0, 1000.0)


if __name__ == "__main__":
    unittest.main()
