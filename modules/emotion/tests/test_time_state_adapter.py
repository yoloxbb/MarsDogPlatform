import json
import unittest

from marsdog_ros2.time_state_adapter import (
    GetEnergyElapsedSecondsPerDemandTickValue,
    GetTimeContextDateTimeValue,
    GetTimeStateMessageValue,
)


class FakeStringMessage:
    """模拟 std_msgs/String。"""

    def __init__(self, data: str) -> None:
        """保存 JSON 字符串。"""
        self.data = data


class TimeStateAdapterTest(unittest.TestCase):
    def _GetPayload(self) -> dict:
        """构造有效统一时间消息。"""
        return {
            "schema_version": "1.0",
            "timestamp": 1000.0,
            "event_type": "TIME_TICK",
            "tickSequence": 12,
            "timeContext": {
                "mode": "custom",
                "scale": 7,
                "revision": 1,
                "virtualStartDateTime": "2026-07-16T06:00:00+08:00",
                "virtualDateTime": "2026-07-16T06:00:12+08:00",
            },
        }

    def test_accepts_dict_json_and_string_message(self):
        """适配器应接受三种常用输入形式。"""
        payload = self._GetPayload()

        self.assertEqual(GetTimeStateMessageValue(payload), payload)
        self.assertEqual(GetTimeStateMessageValue(json.dumps(payload)), payload)
        self.assertEqual(
            GetTimeStateMessageValue(FakeStringMessage(json.dumps(payload))),
            payload,
        )

    def test_rejects_unknown_event_or_missing_context(self):
        """未知时间事件和缺少上下文的消息应被忽略。"""
        payload = self._GetPayload()
        payload["event_type"] = "UNKNOWN"
        self.assertEqual(GetTimeStateMessageValue(payload), {})
        self.assertEqual(
            GetTimeStateMessageValue({"event_type": "TIME_TICK"}),
            {},
        )

    def test_accepts_discrete_test_time_step(self):
        """适配器应接受凌晨场景使用的离散测试时间步骤。"""
        payload = self._GetPayload()
        payload["event_type"] = "TIME_TEST_STEP"

        self.assertEqual(GetTimeStateMessageValue(payload), payload)

    def test_accepts_continuous_midnight_acceleration_events(self):
        """适配器应接受任意基础倍率的凌晨加速步骤和切换事件。"""
        for eventType in (
            "TIME_ACCELERATED_STEP",
            "TIME_ACCELERATION_CHANGED",
        ):
            payload = self._GetPayload()
            payload["event_type"] = eventType
            self.assertEqual(GetTimeStateMessageValue(payload), payload)

    def test_parses_timezone_aware_context_datetime(self):
        """时间字段必须是带时区的 ISO 8601。"""
        payload = self._GetPayload()

        value = GetTimeContextDateTimeValue(payload, "virtualDateTime")

        self.assertIsNotNone(value)
        self.assertEqual(value.hour, 6)
        payload["timeContext"]["virtualDateTime"] = "2026-07-16T06:00:12"
        self.assertIsNone(GetTimeContextDateTimeValue(payload, "virtualDateTime"))

    def test_normal_time_tick_uses_ten_virtual_minutes_for_energy(self):
        """普通需求 Tick 应按600秒虚拟经过时间结算电池。"""
        payload = self._GetPayload()

        self.assertEqual(
            GetEnergyElapsedSecondsPerDemandTickValue(payload),
            600.0,
        )

    def test_midnight_steps_use_real_duration_at_one_times_speed(self):
        """两类凌晨离散步骤都应把30秒平均到36步进行耗电。"""
        productionPayload = self._GetPayload()
        productionPayload["event_type"] = "TIME_ACCELERATED_STEP"
        productionPayload["timeContext"]["midnightAcceleration"] = {
            "durationSeconds": 30.0,
            "stepCount": 36,
        }
        testPayload = self._GetPayload()
        testPayload["event_type"] = "TIME_TEST_STEP"
        testPayload["testScenario"] = {
            "scenarioDurationSeconds": 30.0,
            "stepCount": 36,
        }

        self.assertAlmostEqual(
            GetEnergyElapsedSecondsPerDemandTickValue(productionPayload),
            30.0 / 36.0,
        )
        self.assertAlmostEqual(
            GetEnergyElapsedSecondsPerDemandTickValue(testPayload),
            30.0 / 36.0,
        )

    def test_invalid_midnight_duration_does_not_fabricate_energy_drain(self):
        """凌晨加速元数据非法时不得按600秒错误扣减电池。"""
        payload = self._GetPayload()
        payload["event_type"] = "TIME_ACCELERATED_STEP"
        payload["timeContext"]["midnightAcceleration"] = {
            "durationSeconds": "bad",
            "stepCount": 36,
        }

        self.assertEqual(
            GetEnergyElapsedSecondsPerDemandTickValue(payload),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
