import json
import unittest

from marsdog_core import MarsdogEmotionSystem, MarsdogNeedSystem
from marsdog_ros2.perception_adapter import (
    ApplyAudioEventMessage,
    ApplyTactileEventMessage,
    ApplyVisualEventMessage,
)


class DummyMessage:
    """模拟 std_msgs/String。"""

    def __init__(self, data: str) -> None:
        """保存 data 字段。"""
        self.data = data


class PerceptionAdapterTest(unittest.TestCase):
    def test_visual_event_updates_need_owner_presence(self):
        """visual_event.events 中主人事件应更新需求系统主人在场状态。"""
        system = MarsdogNeedSystem()

        events = ApplyVisualEventMessage(
            system,
            {
                "events": ["EVT_VISION_MASTER", "EVT_VISION_ANIMAL_GREET"],
                "tracked_objects": [{"label": "dog", "tracking_id": "dog-1", "confidence": 0.9}],
            },
        )

        self.assertEqual(events, ["EVT_VISION_MASTER", "EVT_VISION_ANIMAL_GREET"])
        self.assertTrue(system.state.ownerPresent)

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

    def test_tactile_event_updates_emotion_system(self):
        """ONE1000 摸头事件应进入既有触觉情绪映射。"""
        system = MarsdogEmotionSystem()
        beforeEmotions = dict(system.state.emotions)

        events = ApplyTactileEventMessage(
            system,
            {"event_type": "EVT_TACTILE_HEAD_PET", "source": "ONE1000"},
        )

        self.assertEqual(events, ["EVT_TACTILE_HEAD_PET"])
        self.assertEqual(
            system.GetEmotionValue("Joy") - beforeEmotions["Joy"],
            25,
        )
        self.assertEqual(
            system.GetEmotionValue("Calm") - beforeEmotions["Calm"],
            15,
        )
        self.assertEqual(
            system.GetEmotionValue("Excite") - beforeEmotions["Excite"],
            5,
        )

    def test_perception_events_deduplicate_same_name_for_ten_seconds(self):
        """声音、视觉和触摸入口都应统一抑制10秒内的同名事件。"""
        cases = (
            (
                ApplyAudioEventMessage,
                {"event_type": "EVT_VOICE_PRAISE"},
                ["EVT_VOICE_PRAISE"],
            ),
            (
                ApplyVisualEventMessage,
                {"events": ["EVT_VISION_TOY", "EVT_VISION_TOY"]},
                ["EVT_VISION_TOY"],
            ),
            (
                ApplyTactileEventMessage,
                {"event_type": "EVT_TACTILE_HEAD_PET"},
                ["EVT_TACTILE_HEAD_PET"],
            ),
        )

        for applyMessage, payload, expectedEvents in cases:
            with self.subTest(event=expectedEvents[0]):
                system = MarsdogEmotionSystem(eventTimeProvider=lambda: 100.0)
                self.assertEqual(applyMessage(system, payload), expectedEvents)
                emotionsAfterFirstMessage = system.GetAllEmotions()
                self.assertEqual(applyMessage(system, payload), [])
                self.assertEqual(system.GetAllEmotions(), emotionsAfterFirstMessage)

    def test_tactile_event_does_not_change_internal_needs(self):
        """临时摸头传感器只影响情绪，不改变内部需求。"""
        system = MarsdogNeedSystem()
        beforeDemands = dict(system.state.demands)

        events = ApplyTactileEventMessage(
            system,
            {"event_type": "EVT_TACTILE_HEAD_PET"},
        )

        self.assertEqual(events, ["EVT_TACTILE_HEAD_PET"])
        self.assertEqual(system.state.demands, beforeDemands)

    def test_invalid_json_message_is_ignored(self):
        """非法 JSON 输入不应修改系统状态。"""
        system = MarsdogEmotionSystem()

        events = ApplyAudioEventMessage(system, DummyMessage("{not json"))

        self.assertEqual(events, [])
        self.assertEqual(system.GetEmotionValue("Joy"), 0)


if __name__ == "__main__":
    unittest.main()
