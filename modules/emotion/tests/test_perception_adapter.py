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

    def test_family_member_visual_event_preserves_need_presence_side_effect(self):
        system = MarsdogNeedSystem()

        events = ApplyVisualEventMessage(
            system,
            {"events": ["EVT_VISION_FAMILY_MEMBER"]},
        )

        self.assertEqual(events, ["EVT_VISION_FAMILY_MEMBER"])
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

    def test_family_member_keeps_known_person_emotion_mapping(self):
        system = MarsdogEmotionSystem()
        before = system.GetAllEmotions()

        events = ApplyVisualEventMessage(
            system,
            {"events": ["EVT_VISION_FAMILY_MEMBER"]},
        )

        self.assertEqual(events, ["EVT_VISION_FAMILY_MEMBER"])
        self.assertEqual(system.GetEmotionValue("Joy") - before["Joy"], 25)
        self.assertEqual(system.GetEmotionValue("Excite") - before["Excite"], 15)
        self.assertEqual(system.GetEmotionValue("Calm") - before["Calm"], 10)

    def test_master_and_family_member_share_one_known_person_delta_per_snapshot(self):
        system = MarsdogEmotionSystem()
        before = system.GetAllEmotions()

        events = ApplyVisualEventMessage(
            system,
            {
                "events": ["EVT_VISION_MASTER", "EVT_VISION_FAMILY_MEMBER"],
            },
        )

        self.assertEqual(events, ["EVT_VISION_MASTER"])
        self.assertEqual(system.GetEmotionValue("Joy") - before["Joy"], 25)
        self.assertEqual(system.GetEmotionValue("Excite") - before["Excite"], 15)
        self.assertEqual(system.GetEmotionValue("Calm") - before["Calm"], 10)

    def test_toy_event_instance_is_applied_once_across_long_hold(self):
        """同一个玩具周期即使 HOLD 超过通用窗口也只应用一次。"""
        now = [100.0]
        system = MarsdogEmotionSystem(eventTimeProvider=lambda: now[0])
        payload = {
            "events": ["EVT_VISION_TOY"],
            "event_instances": {"EVT_VISION_TOY": {"event_id": "toy-cycle-1"}},
        }

        self.assertEqual(ApplyVisualEventMessage(system, payload), ["EVT_VISION_TOY"])
        firstEmotions = system.GetAllEmotions()
        now[0] += 15.0
        self.assertEqual(ApplyVisualEventMessage(system, payload), [])
        self.assertEqual(system.GetAllEmotions(), firstEmotions)

    def test_new_toy_event_instance_bypasses_generic_same_name_window(self):
        """新的玩具周期可在同名十秒窗口内独立应用一次。"""
        now = [100.0]
        system = MarsdogEmotionSystem(eventTimeProvider=lambda: now[0])

        first = {
            "events": ["EVT_VISION_TOY"],
            "event_instances": {"EVT_VISION_TOY": {"event_id": "toy-cycle-1"}},
        }
        second = {
            "events": ["EVT_VISION_TOY"],
            "event_instances": {"EVT_VISION_TOY": {"event_id": "toy-cycle-2"}},
        }

        self.assertEqual(ApplyVisualEventMessage(system, first), ["EVT_VISION_TOY"])
        firstEmotions = system.GetAllEmotions()
        now[0] += 1.0
        self.assertEqual(ApplyVisualEventMessage(system, second), ["EVT_VISION_TOY"])
        self.assertEqual(
            system.GetEmotionValue("Excite") - firstEmotions["Excite"],
            30,
        )
        self.assertEqual(
            system.GetEmotionValue("Curious") - firstEmotions["Curious"],
            23,
        )
        self.assertEqual(system.GetEmotionValue("Joy") - firstEmotions["Joy"], 15)

    def test_duplicate_toy_event_strings_with_one_instance_apply_once(self):
        """同一快照重复列出玩具事件仍只按一个实例增量一次。"""
        system = MarsdogEmotionSystem(eventTimeProvider=lambda: 100.0)

        events = ApplyVisualEventMessage(
            system,
            {
                "events": ["EVT_VISION_TOY", "EVT_VISION_TOY"],
                "event_instances": {
                    "EVT_VISION_TOY": {"event_id": "toy-cycle-duplicate"}
                },
            },
        )

        self.assertEqual(events, ["EVT_VISION_TOY"])
        self.assertEqual(system.GetEmotionValue("Excite"), 30)
        self.assertEqual(system.GetEmotionValue("Curious"), 23)
        self.assertEqual(system.GetEmotionValue("Joy"), 15)

    def test_legacy_toy_visual_event_without_instance_keeps_name_window(self):
        """没有实例 ID 的 schema v1 老载荷仍使用既有同名时间窗口。"""
        now = [100.0]
        system = MarsdogEmotionSystem(eventTimeProvider=lambda: now[0])
        legacyPayload = {"events": ["EVT_VISION_TOY"]}

        self.assertEqual(
            ApplyVisualEventMessage(system, legacyPayload), ["EVT_VISION_TOY"]
        )
        firstEmotions = system.GetAllEmotions()
        now[0] += 9.0
        self.assertEqual(ApplyVisualEventMessage(system, legacyPayload), [])
        self.assertEqual(system.GetAllEmotions(), firstEmotions)
        now[0] += 1.0
        self.assertEqual(
            ApplyVisualEventMessage(system, legacyPayload), ["EVT_VISION_TOY"]
        )

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
