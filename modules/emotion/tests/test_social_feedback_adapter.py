import json
import random
import unittest

from marsdog_core import MarsdogBehaviorSystem
from marsdog_ros2.social_feedback_adapter import ApplySocialFeedbackMessage


class DummyMessage:
    """测试用 ROS2 String 消息。"""

    def __init__(self, data: str) -> None:
        """初始化消息内容。"""
        self.data = data


class SocialFeedbackAdapterTest(unittest.TestCase):
    def test_social_feedback_json_settles_waiting_interaction(self):
        """social_feedback JSON 应结算匹配的等待会话。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)

        for _ in range(20):
            command = system.GetCurrentActionCommand()
            if command is None:
                break
            system.OnActionFeedback(command["commandId"], command["concreteAction"], "SUCCESS")

        status = system.GetSocialInteractionStatus()
        message = DummyMessage(
            json.dumps(
                {
                    "interactionId": status["interactionId"],
                    "targetType": status["targetType"],
                    "responseType": "RESPONDED",
                    "metadata": {"source": "test"},
                }
            )
        )

        self.assertTrue(ApplySocialFeedbackMessage(system, message))
        self.assertEqual(system.GetDemandValue("Social"), 60)

    def test_invalid_social_feedback_is_rejected(self):
        """非法或空反馈消息应返回失败。"""
        system = MarsdogBehaviorSystem()

        self.assertFalse(ApplySocialFeedbackMessage(system, "not-json"))
        self.assertFalse(ApplySocialFeedbackMessage(system, {}))


if __name__ == "__main__":
    unittest.main()
