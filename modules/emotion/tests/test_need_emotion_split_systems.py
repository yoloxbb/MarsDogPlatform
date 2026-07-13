import random
import unittest

from marsdog_core.emotion_system import MarsdogEmotionSystem
from marsdog_core.need_system import MarsdogNeedSystem
from marsdog_ros2.behavior_result_adapter import ApplyBehaviorResultMessage
from marsdog_ros2.perception_adapter import ApplyAudioEventMessage, ApplyVisualEventMessage


class NeedEmotionSplitSystemTest(unittest.TestCase):
    def test_need_system_has_no_behavior_runtime_dependencies(self):
        """需求系统不应创建仲裁器、行为树或动作规划器。"""
        system = MarsdogNeedSystem()

        self.assertFalse(hasattr(system, "arbiter"))
        self.assertFalse(hasattr(system, "actionPlanner"))
        self.assertFalse(hasattr(system, "behaviorTreeRunner"))

    def test_need_signals_include_threshold_and_overflow(self):
        """需求状态输出应包含触发和满溢信号。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 95)

        state = system.GetInternalNeedStateValue(timestamp=1.0)

        self.assertTrue(state["demands"]["Hunger"]["triggered"])
        self.assertTrue(state["demands"]["Hunger"]["overflow"])
        self.assertEqual(state["demands"]["Hunger"]["level"], "OVERFLOW")
        self.assertEqual(state["demands"]["Hunger"]["levelEvent"], "NEED_HUNGER_OVERFLOW")
        self.assertEqual(state["levelEvents"]["Hunger"], "NEED_HUNGER_OVERFLOW")
        self.assertEqual(state["triggered"][0]["type"], "Hunger")

        events = system.GetDemandSignalEventsValue(timestamp=2.0)

        self.assertEqual(state["levelEvents"][events[0]["demand"]], events[0]["event_type"])

    def test_eat_result_updates_internal_demands(self):
        """进食完成结果应降低 Hunger 并联动 Bladder 与 Cleanliness。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 95)
        system.SetDemandValue("Bladder", 0)
        system.SetDemandValue("Cleanliness", 10)

        accepted = system.OnBehaviorResultEvent(
            {
                "action_type": "ACTION_EAT",
                "result_type": "COMPLETED",
                "metadata": {
                    "foodType": "NormalFood",
                    "portions": 1,
                    "eatEfficiency": "Full",
                },
            }
        )

        self.assertTrue(accepted)
        self.assertEqual(system.GetDemandValue("Hunger"), 75)
        self.assertEqual(system.GetDemandValue("Bladder"), 25)
        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)

    def test_interrupted_behavior_result_reduces_mapped_demand(self):
        """行为中断结果应按 actionDemandMap 扣减对应需求。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)

        accepted = system.OnBehaviorResultEvent(
            {"action_type": "ACTION_EAT", "result_type": "INTERRUPTED"}
        )

        self.assertTrue(accepted)
        self.assertEqual(system.GetDemandValue("Hunger"), 60)

    def test_visual_and_audio_adapters_forward_to_split_systems(self):
        """新版感知适配器应转发 visual_event 和 audio_event。"""
        needSystem = MarsdogNeedSystem()
        emotionSystem = MarsdogEmotionSystem()

        visualEvents = ApplyVisualEventMessage(
            needSystem,
            {"events": ["EVT_VISION_MASTER"], "active_target": {"identity": "alice"}},
        )
        audioEvents = ApplyAudioEventMessage(
            emotionSystem,
            {"event_type": "EVT_VOICE_CALL_NAME"},
        )

        self.assertEqual(visualEvents, ["EVT_VISION_MASTER"])
        self.assertTrue(needSystem.state.ownerPresent)
        self.assertEqual(audioEvents, ["EVT_VOICE_CALL_NAME"])
        self.assertGreater(emotionSystem.GetEmotionValue("Joy"), 0)

    def test_emotion_system_applies_event_personality_and_decay(self):
        """情绪系统应按事件基础值、性格系数和自然衰减更新情绪。"""
        system = MarsdogEmotionSystem(randomGenerator=random.Random(1))

        self.assertTrue(system.ApplyEmotionEvent("EVT_VOICE_PRAISE", {"masterId": True}))
        self.assertEqual(system.GetEmotionValue("Joy"), 36)
        self.assertEqual(system.GetEmotionValue("Excite"), 24)
        self.assertEqual(system.GetEmotionValue("Calm"), 36)

        system.ApplyEmotionDecay(2)

        self.assertEqual(system.GetEmotionValue("Joy"), 32)
        self.assertEqual(system.GetEmotionValue("Excite"), 18)
        self.assertEqual(system.GetEmotionValue("Calm"), 36)

    def test_emotion_state_includes_level_ranges(self):
        """情绪状态应按新区间表输出等级和事件名。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Joy", 72)
        system.SetEmotionValue("Excite", 39)

        state = system.GetEmotionStateValue(timestamp=1.0)

        self.assertEqual(state["emotions"]["Joy"]["level"], "MID")
        self.assertEqual(state["emotions"]["Joy"]["levelEvent"], "EMO_JOY_MID")
        self.assertEqual(state["levelEvents"]["Joy"], "EMO_JOY_MID")
        self.assertIsNone(state["levelEvents"]["Excite"])
        self.assertEqual(state["emotions"]["Joy"]["levelRange"], [61, 85])
        self.assertFalse(state["emotions"]["Excite"]["levelActive"])
        self.assertEqual(state["dominantEmotionSignal"]["eventType"], "EMO_JOY_MID")

        events = system.GetEmotionSignalEventsValue(timestamp=2.0)

        self.assertEqual(state["levelEvents"][events[0]["emotion"]], events[0]["event_type"])

    def test_emotion_signal_events_emit_only_on_level_change(self):
        """情绪区间事件只应在等级或主导情绪变化时输出一次。"""
        system = MarsdogEmotionSystem()

        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=1.0), [])

        system.SetEmotionValue("Joy", 35)
        events = system.GetEmotionSignalEventsValue(timestamp=2.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "EMO_JOY_LOW")
        self.assertEqual(events[0]["trigger"], "LEVEL_CHANGED_AND_DOMINANT_CHANGED")
        self.assertTrue(events[0]["isDominant"])
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=3.0), [])

        system.SetEmotionValue("Joy", 50)
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=4.0), [])

        system.SetEmotionValue("Joy", 70)
        events = system.GetEmotionSignalEventsValue(timestamp=5.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "EMO_JOY_MID")
        self.assertEqual(events[0]["range"], [61, 85])

    def test_visual_event_updates_emotions_from_events_array(self):
        """visual_event.events[] 中的 EVT_VISION_* 应进入情绪映射表。"""
        system = MarsdogEmotionSystem()

        events = system.OnVisualEvent({"events": ["EVT_VISION_TOY"]})

        self.assertEqual(events, ["EVT_VISION_TOY"])
        self.assertEqual(system.GetEmotionValue("Excite"), 30)
        self.assertEqual(system.GetEmotionValue("Curious"), 23)
        self.assertEqual(system.GetEmotionValue("Joy"), 15)

    def test_behavior_result_adapter_updates_need_and_emotion_systems(self):
        """behavior/result_event 适配器应能分别驱动需求和情绪系统。"""
        needSystem = MarsdogNeedSystem()
        emotionSystem = MarsdogEmotionSystem(randomGenerator=random.Random(1))
        needSystem.SetDemandValue("Cleanliness", 80)

        message = {
            "action_type": "ACTION_GROOM",
            "result_type": "COMPLETED",
            "metadata": {},
        }

        self.assertTrue(ApplyBehaviorResultMessage(needSystem, message))
        self.assertTrue(ApplyBehaviorResultMessage(emotionSystem, message))
        self.assertEqual(needSystem.GetDemandValue("Cleanliness"), 30)
        self.assertGreaterEqual(emotionSystem.GetEmotionValue("Joy"), 10)

    def test_behavior_result_event_id_is_deduplicated(self):
        """同一个 event_id 的行为结果只能结算一次。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)
        message = {
            "event_id": "result-duplicate-1",
            "action_type": "ACTION_EAT",
            "result_type": "COMPLETED",
            "metadata": {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"},
        }

        self.assertTrue(system.OnBehaviorResultEvent(message))
        self.assertFalse(system.OnBehaviorResultEvent(message))
        self.assertEqual(system.GetDemandValue("Hunger"), 60)

    def test_behavior_result_rejects_demand_action_mismatch(self):
        """demand_type 与 action_type 映射不一致时应拒绝处理。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)

        accepted = system.OnBehaviorResultEvent(
            {
                "event_id": "result-mismatch-1",
                "action_type": "ACTION_EAT",
                "demand_type": "Bladder",
                "result_type": "COMPLETED",
                "metadata": {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"},
            }
        )

        self.assertFalse(accepted)
        self.assertEqual(system.GetDemandValue("Hunger"), 80)

    def test_emotion_result_ignores_unknown_action(self):
        """情绪系统不应因无关或未知 action 结果改变情绪。"""
        system = MarsdogEmotionSystem(randomGenerator=random.Random(1))

        accepted = system.OnBehaviorResultEvent(
            {
                "event_id": "result-unknown-action-1",
                "action_type": "ACTION_PET",
                "result_type": "COMPLETED",
                "metadata": {},
            }
        )

        self.assertFalse(accepted)
        self.assertEqual(system.GetEmotionValue("Joy"), 0)

    def test_recharge_result_rejects_invalid_energy_value(self):
        """充电结果里的 energyValue 非数字时不应写入需求。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Energy", 5)

        accepted = system.OnBehaviorResultEvent(
            {
                "event_id": "result-invalid-energy-1",
                "action_type": "ACTION_RECHARGE",
                "result_type": "COMPLETED",
                "metadata": {"energyValue": "bad"},
            }
        )

        self.assertFalse(accepted)
        self.assertEqual(system.GetDemandValue("Energy"), 5)


if __name__ == "__main__":
    unittest.main()
