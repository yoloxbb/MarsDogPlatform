import json
import unittest

from marsdog_core import MarsdogEmotionSystem, MarsdogNeedSystem, MarsdogPersonalitySystem
from marsdog_ros2.personality_adapter import ApplyPersonalityStateMessage


class DummyMessage:
    """模拟 std_msgs/String。"""

    def __init__(self, data: str) -> None:
        """保存 data 字段。"""
        self.data = data


class PersonalityApiTest(unittest.TestCase):
    def test_profile_state_outputs_params_and_coefficients(self):
        """性格状态应输出参数和自动计算的只读系数。"""
        system = MarsdogPersonalitySystem(timeProvider=lambda: 1.0)

        self.assertTrue(system.SetPersonalityProfileValue("SunnyExplorer"))
        state = system.GetPersonalityStateValue()

        self.assertEqual(state["schema_version"], "1.0")
        self.assertEqual(state["timestamp"], 1.0)
        self.assertEqual(state["profile"], "SunnyExplorer")
        self.assertEqual(state["params"], {"A": 90, "O": 80, "E": 95, "C": 70})
        self.assertAlmostEqual(state["coefficients"]["Joy"], 1.82)
        self.assertAlmostEqual(state["coefficients"]["Social"], 1.82)
        self.assertAlmostEqual(state["coefficients"]["Fear"], 0.6)

    def test_custom_params_are_validated(self):
        """自定义 A/O/E/C 必须完整且在 0-100 范围内。"""
        system = MarsdogPersonalitySystem()

        self.assertTrue(system.SetPersonalityParamsValue({"A": 85, "O": 75, "E": 30, "C": 40}))
        self.assertEqual(system.GetPersonalityProfileValue(), "Custom")
        self.assertEqual(system.GetAllPersonalityParams()["A"], 85)

        self.assertFalse(system.SetPersonalityParamsValue({"A": 85, "O": 75, "E": 30}))
        self.assertFalse(system.SetPersonalityParamValue("A", 101))
        self.assertFalse(system.SetPersonalityParamValue("bad", 50))
        self.assertEqual(system.GetAllPersonalityParams()["A"], 85)

    def test_single_param_switches_to_custom(self):
        """单独设置 A/O/E/C 时应切换为 Custom。"""
        system = MarsdogPersonalitySystem()
        self.assertTrue(system.SetPersonalityProfileValue("SunnyExplorer"))

        self.assertTrue(system.SetPersonalityParamValue("A", 60))

        self.assertEqual(system.GetPersonalityProfileValue(), "Custom")
        self.assertEqual(system.GetAllPersonalityParams()["A"], 60)

    def test_personality_state_message_syncs_need_and_emotion_systems(self):
        """personality/state 应能同步需求和情绪系统的性格参数。"""
        payload = {
            "profile": "SunnyExplorer",
            "params": {"A": 90, "O": 80, "E": 95, "C": 70},
            "coefficients": {"Joy": 999},
        }
        needSystem = MarsdogNeedSystem()
        emotionSystem = MarsdogEmotionSystem()

        self.assertTrue(ApplyPersonalityStateMessage(needSystem, DummyMessage(json.dumps(payload))))
        self.assertTrue(ApplyPersonalityStateMessage(emotionSystem, payload))

        self.assertEqual(needSystem.GetPersonalityProfileValue(), "SunnyExplorer")
        self.assertEqual(emotionSystem.GetAllPersonalityParams()["E"], 95)
        self.assertAlmostEqual(emotionSystem.GetEmotionPersonalityCoefficientValue("Joy"), 1.82)

    def test_invalid_personality_state_message_is_ignored(self):
        """非法 personality/state 不应修改系统状态。"""
        system = MarsdogNeedSystem()

        self.assertFalse(ApplyPersonalityStateMessage(system, DummyMessage("{not json")))
        self.assertFalse(
            ApplyPersonalityStateMessage(
                system,
                {"profile": "SunnyExplorer", "params": {"A": 90, "O": 80, "E": 95}},
            )
        )
        self.assertEqual(system.GetAllPersonalityParams(), {"A": 50, "O": 50, "E": 50, "C": 50})


if __name__ == "__main__":
    unittest.main()
