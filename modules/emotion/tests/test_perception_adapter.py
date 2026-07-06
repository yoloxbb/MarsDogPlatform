import json
import unittest

from marsdog_core import MarsdogEmotionSystem, MarsdogNeedSystem
from marsdog_ros2.perception_adapter import ApplyAudioEventMessage, ApplyVisualEventMessage


class DummyMessage:
    """模拟 std_msgs/String。"""

    def __init__(self, data: str) -> None:
        """保存 data 字段。"""
        self.data = data


class PerceptionAdapterTest(unittest.TestCase):
    def test_visual_event_updates_need_context(self):
        """visual_event.events 应更新需求系统的人/动物可见上下文。"""
        system = MarsdogNeedSystem()

        events = ApplyVisualEventMessage(
            system,
            {
                "events": ["EVT_VISION_MASTER", "EVT_VISION_ANIMAL_GREET"],
                "tracked_objects": [{"label": "dog", "tracking_id": "dog-1", "confidence": 0.9}],
            },
        )

        self.assertEqual(events, ["EVT_VISION_MASTER", "EVT_VISION_ANIMAL_GREET"])
        self.assertTrue(system.state.socialHumanVisible)
        self.assertTrue(system.state.socialAnimalVisible)

    def test_visual_event_registers_exploration_target(self):
        """tracked_objects 应登记为探索候选目标。"""
        system = MarsdogNeedSystem()

        ApplyVisualEventMessage(
            system,
            {
                "tracked_objects": [
                    {"label": "delivery_box", "tracking_id": "box-1", "confidence": 0.8}
                ]
            },
        )

        context = system.GetExplorationContext()
        self.assertEqual(context["pendingTargetId"], "box-1")
        self.assertEqual(system.state.pendingEvents[-1].eventTag, "NewObject")

    def test_audio_event_updates_need_owner_presence(self):
        """主人声纹或叫名字事件应更新需求系统主人在场状态。"""
        system = MarsdogNeedSystem()

        events = ApplyAudioEventMessage(system, {"event_type": "EVT_VOICE_MASTER_ID"})

        self.assertEqual(events, ["EVT_VOICE_MASTER_ID"])
        self.assertTrue(system.state.ownerPresent)

    def test_audio_event_updates_emotion_system(self):
        """audio_event 的 EVT_VOICE_* 应进入情绪映射。"""
        system = MarsdogEmotionSystem()

        events = ApplyAudioEventMessage(
            system,
            DummyMessage(json.dumps({"event_type": "EVT_VOICE_PRAISE", "masterId": True})),
        )

        self.assertEqual(events, ["EVT_VOICE_PRAISE"])
        self.assertEqual(system.GetEmotionValue("Joy"), 36)
        self.assertEqual(system.GetEmotionValue("Excite"), 24)

    def test_visual_event_updates_emotion_system_from_events_array(self):
        """visual_event.events[] 中的 EVT_VISION_* 应逐个更新情绪。"""
        system = MarsdogEmotionSystem()

        events = ApplyVisualEventMessage(system, {"events": ["EVT_VISION_TOY"]})

        self.assertEqual(events, ["EVT_VISION_TOY"])
        self.assertEqual(system.GetEmotionValue("Excite"), 30)
        self.assertEqual(system.GetEmotionValue("Curious"), 23)

    def test_invalid_json_message_is_ignored(self):
        """非法 JSON 输入不应修改系统状态。"""
        system = MarsdogEmotionSystem()

        events = ApplyAudioEventMessage(system, DummyMessage("{not json"))

        self.assertEqual(events, [])
        self.assertEqual(system.GetEmotionValue("Joy"), 0)


if __name__ == "__main__":
    unittest.main()
