import json
import unittest

from marsdog_ros2.time_state_adapter import (
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

    def test_parses_timezone_aware_context_datetime(self):
        """时间字段必须是带时区的 ISO 8601。"""
        payload = self._GetPayload()

        value = GetTimeContextDateTimeValue(payload, "virtualDateTime")

        self.assertIsNotNone(value)
        self.assertEqual(value.hour, 6)
        payload["timeContext"]["virtualDateTime"] = "2026-07-16T06:00:12"
        self.assertIsNone(GetTimeContextDateTimeValue(payload, "virtualDateTime"))


if __name__ == "__main__":
    unittest.main()
