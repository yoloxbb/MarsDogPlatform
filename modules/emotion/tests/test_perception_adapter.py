import json
import unittest

from marsdog_core import MarsdogBehaviorSystem
from marsdog_ros2.perception_adapter import ApplyInteractionEventMessage, ApplyObservationMessage


class DummyMessage:
    def __init__(self, data):
        """构造一个简化的 ROS2 String 消息。"""
        self.data = data


class PerceptionAdapterTest(unittest.TestCase):
    def test_observation_human_only_updates_social_visibility(self):
        """observation 中看到人体只应更新社交目标可见性。"""
        system = MarsdogBehaviorSystem()
        payload = {"humans": [{"confidence": 0.86}], "faces": [], "tracked_objects": []}

        events = ApplyObservationMessage(system, DummyMessage(json.dumps(payload)))

        self.assertEqual(events, ["HumanVisible"])
        self.assertTrue(system.state.socialHumanVisible)
        self.assertEqual(system.state.pendingEvents, [])

    def test_observation_animal_maps_to_animal_approach(self):
        """跟踪到狗猫等动物时应生成 AnimalApproach。"""
        system = MarsdogBehaviorSystem()
        payload = {"tracked_objects": [{"label": "dog", "confidence": 0.88}]}

        events = ApplyObservationMessage(system, payload)

        self.assertEqual(events, ["AnimalApproach"])
        self.assertTrue(system.state.socialAnimalVisible)
        self.assertEqual(system.state.pendingEvents[0].eventTag, "AnimalApproach")

    def test_observation_tracked_object_maps_to_new_object(self):
        """observation 中持续跟踪物体应转为 NewObject。"""
        system = MarsdogBehaviorSystem()
        payload = {"tracked_objects": [{"label": "ball", "confidence": 0.82}]}

        events = ApplyObservationMessage(system, payload)

        self.assertEqual(events, ["NewObject"])
        self.assertEqual(system.state.pendingEvents[0].eventTag, "NewObject")
        self.assertEqual(system.state.pendingEvents[0].metadata["value"], 82.0)
        self.assertEqual(system.state.explorationPendingTargetType, "GenericObject")

    def test_observation_maps_specific_object_and_explicit_novelty(self):
        """特定物品标签和显式新旧标记应进入探索上下文。"""
        system = MarsdogBehaviorSystem()
        payload = {
            "tracked_objects": [
                {
                    "label": "delivery_box",
                    "tracking_id": "box-1",
                    "confidence": 0.91,
                    "is_new": False,
                }
            ]
        }

        events = ApplyObservationMessage(system, payload)

        self.assertEqual(events, ["OldObject"])
        self.assertEqual(system.state.explorationPendingTargetType, "DeliveryBox")
        self.assertEqual(system.state.explorationPendingTargetId, "box-1")
        self.assertEqual(system.state.explorationPendingDiscoveryType, "Old")

    def test_wakeup_event_maps_to_owner_call(self):
        """interaction_event wakeup 应转为 OwnerCall。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Social", 20)
        payload = {
            "event_type": "wakeup",
            "wake_word": "MarsDog",
            "wake_angle": 85,
            "wake_confidence": 0.9,
        }

        events = ApplyInteractionEventMessage(system, payload)
        system.Tick(currentTime=9)

        self.assertEqual(events, ["OwnerCall"])
        self.assertEqual(system.GetCurrentAction(), "ACTION_SOCIAL_GREET")

    def test_wakeup_speech_intent_are_merged_into_one_owner_round(self):
        """同一 10 秒窗口内的 wakeup/speech/intent 不应重复触发主人互动。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(timeProvider=lambda: now[0])

        wakeupEvents = ApplyInteractionEventMessage(
            system,
            {"event_type": "wakeup", "wake_confidence": 0.9},
        )
        speechEvents = ApplyInteractionEventMessage(
            system,
            {"event_type": "speech", "speaker_confidence": 0.9},
        )
        intentEvents = ApplyInteractionEventMessage(
            system,
            {
                "event_type": "intent",
                "command_id": "CMD_GREETING",
                "intent_category": "social",
            },
        )

        self.assertEqual(wakeupEvents, ["OwnerCall"])
        self.assertEqual(speechEvents, ["VoiceInput"])
        self.assertEqual(intentEvents, [])
        self.assertEqual(
            [event.eventTag for event in system.state.pendingEvents],
            ["OwnerCall", "VoiceInput"],
        )

    def test_owner_left_home_state_adds_social_once(self):
        """明确的主人离家状态应单次增加 Social。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Social", 20)

        ApplyInteractionEventMessage(system, {"event_type": "state", "state": "owner_left_home"})
        ApplyInteractionEventMessage(system, {"event_type": "state", "state": "owner_left_home"})

        self.assertEqual(system.GetDemandValue("Social"), 50)

    def test_danger_event_maps_to_danger_priority(self):
        """interaction_event danger 应进入 Lv.0 生存避险。"""
        system = MarsdogBehaviorSystem()
        payload = {"event_type": "danger", "danger_type": "obstacle", "danger_angle": 10}

        events = ApplyInteractionEventMessage(system, payload)
        system.Tick(currentTime=9)

        self.assertEqual(events, ["Danger"])
        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")

    def test_weightlessness_danger_maps_to_weightlessness(self):
        """danger_type 为失重时应转为 Weightlessness。"""
        system = MarsdogBehaviorSystem()
        payload = {"event_type": "danger", "danger_type": "weightlessness"}

        events = ApplyInteractionEventMessage(system, payload)

        self.assertEqual(events, ["Weightlessness"])
        self.assertEqual(system.state.pendingEvents[0].eventTag, "Weightlessness")

    def test_state_lights_off_forces_sleepiness(self):
        """state lights_off 应立即设置关灯并刷新困倦。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 10)
        payload = {"event_type": "state", "state": "lights_off"}

        events = ApplyInteractionEventMessage(system, payload)
        system.Tick(currentTime=22, applyDemandGrowth=False)

        self.assertEqual(events, ["StateChange"])
        self.assertTrue(system.state.lightsOff)
        self.assertEqual(system.GetDemandValue("Sleepiness"), 90)
        self.assertEqual(system.GetCurrentAction(), "ACTION_SLEEP")

    def test_invalid_json_is_ignored(self):
        """非法 JSON 消息不应产生事件。"""
        system = MarsdogBehaviorSystem()

        events = ApplyInteractionEventMessage(system, DummyMessage("{bad json"))

        self.assertEqual(events, [])
        self.assertEqual(system.state.pendingEvents, [])


if __name__ == "__main__":
    unittest.main()
