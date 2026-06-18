import json
import random
import unittest

from marsdog_core import MarsdogBehaviorSystem
from marsdog_ros2.action_feedback_adapter import ApplyActionFeedbackMessage


class Message:
    """测试用的简易 ROS2 String 消息。"""

    def __init__(self, data: str) -> None:
        """初始化消息内容。"""
        self.data = data


class ActionFeedbackAdapterTest(unittest.TestCase):
    def test_apply_action_feedback_message_from_json_string(self):
        """JSON 字符串反馈应能推进核心行为树。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        command = system.GetCurrentActionCommand()

        payload = {
            "commandId": command["commandId"],
            "actionName": command["concreteAction"],
            "status": "SUCCESS",
        }

        self.assertTrue(ApplyActionFeedbackMessage(system, json.dumps(payload)))
        self.assertEqual(system.GetFinishedConcreteActions(), ["ACT_RUN_TO_BOWL"])

    def test_apply_action_feedback_message_from_ros_string_message(self):
        """带 data 字段的 ROS2 String 消息应能作为反馈输入。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=22)
        command = system.GetCurrentActionCommand()

        payload = {
            "command_id": command["commandId"],
            "action_name": command["concreteAction"],
            "status": "SUCCESS",
        }

        self.assertTrue(ApplyActionFeedbackMessage(system, Message(json.dumps(payload))))

    def test_invalid_feedback_message_is_rejected(self):
        """非法反馈消息应返回失败。"""
        system = MarsdogBehaviorSystem()

        self.assertFalse(ApplyActionFeedbackMessage(system, "not-json"))
        self.assertFalse(ApplyActionFeedbackMessage(system, {}))


if __name__ == "__main__":
    unittest.main()
