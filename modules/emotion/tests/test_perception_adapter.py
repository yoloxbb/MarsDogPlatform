import json
import unittest

from marsdog_core import MarsdogBehaviorSystem
from marsdog_ros2.perception_adapter import ApplyInteractionEventMessage, ApplyObservationMessage


class DummyMessage:
    def __init__(self, data):
        """构造一个简化的 ROS2 String 消息。"""
        self.data = data


class PerceptionAdapterTest(unittest.TestCase):
    def test_observation_human_maps_to_human_approach(self):
        """observation 中看到人体应转为 HumanApproach。"""
        system = MarsdogBehaviorSystem()
        payload = {"humans": [{"confidence": 0.86}], "faces": [], "tracked_objects": []}

        events = ApplyObservationMessage(system, DummyMessage(json.dumps(payload)))

        self.assertEqual(events, ["HumanApproach"])
        self.assertEqual(system.state.pendingEvents[0].eventTag, "HumanApproach")
        self.assertEqual(system.state.pendingEvents[0].metadata["humanCount"], 1)

    def test_observation_tracked_object_maps_to_new_object(self):
        """observation 中持续跟踪物体应转为 NewObject。"""
        system = MarsdogBehaviorSystem()
        payload = {"tracked_objects": [{"label": "ball", "confidence": 0.82}]}

        events = ApplyObservationMessage(system, payload)

        self.assertEqual(events, ["NewObject"])
        self.assertEqual(system.state.pendingEvents[0].eventTag, "NewObject")
        self.assertEqual(system.state.pendingEvents[0].metadata["value"], 82.0)

    def test_wakeup_event_maps_to_owner_call(self):
        """interaction_event wakeup 应转为 OwnerCall。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Social", 80)
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
