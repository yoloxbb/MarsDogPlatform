import random
import unittest

from marsdog_core import MarsdogEmotionSystem


class EmotionAPITest(unittest.TestCase):
    def test_get_set_and_delta_clamp_values(self):
        """情绪读写和增量更新都应限制在 0-100。"""
        system = MarsdogEmotionSystem()

        self.assertTrue(system.SetEmotionValue("Joy", 150))
        self.assertEqual(system.GetEmotionValue("Joy"), 100)
        self.assertTrue(system.ApplyEmotionDelta("Joy", -130))
        self.assertEqual(system.GetEmotionValue("Joy"), 0)

    def test_get_dominant_emotion(self):
        """主导情绪应返回当前值最高的情绪。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Fear", 40)

        self.assertEqual(system.GetDominantEmotion(), "Fear")

    def test_emotion_changed_callback(self):
        """情绪变化时应触发注册回调。"""
        system = MarsdogEmotionSystem()
        records = []

        system.OnEmotionChanged(lambda name, old, new: records.append((name, old, new)))
        system.SetEmotionValue("Joy", 10)

        self.assertEqual(records, [("Joy", 0, 10)])

    def test_apply_action_result_emotion(self):
        """行为结果情绪映射仍由情绪系统处理。"""
        system = MarsdogEmotionSystem(randomGenerator=random.Random(1))

        self.assertTrue(system.ApplyActionResultEmotion("DemandSatisfied"))

        self.assertGreaterEqual(system.GetEmotionValue("Joy"), 10)
        self.assertGreaterEqual(system.GetEmotionValue("Calm"), 35)

    def test_apply_emotion_event_uses_personality_and_multiplier(self):
        """外部 EVT_* 情绪事件应乘性格系数和元数据倍率。"""
        system = MarsdogEmotionSystem()

        self.assertTrue(system.ApplyEmotionEvent("EVT_VOICE_PRAISE", {"masterId": True}))

        self.assertEqual(system.GetEmotionValue("Joy"), 36)
        self.assertEqual(system.GetEmotionValue("Excite"), 24)
        self.assertEqual(system.GetEmotionValue("Calm"), 36)

    def test_apply_emotion_decay(self):
        """自然平复应按秒扣减配置情绪，并保持 Anxiety 和 Calm。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Joy", 10)
        system.SetEmotionValue("Excite", 10)
        system.SetEmotionValue("Anxiety", 10)
        system.SetEmotionValue("Calm", 40)

        system.ApplyEmotionDecay(2)

        self.assertEqual(system.GetEmotionValue("Joy"), 6)
        self.assertEqual(system.GetEmotionValue("Excite"), 4)
        self.assertEqual(system.GetEmotionValue("Anxiety"), 10)
        self.assertEqual(system.GetEmotionValue("Calm"), 40)

    def test_anxiety_changes_by_event_but_not_by_time(self):
        """焦虑仍响应外部事件，但不会被自然衰减定时规则降低。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Anxiety", 10)

        self.assertTrue(system.ApplyEmotionEvent("EVT_AUDIO_LOUD"))
        anxietyAfterEvent = system.GetEmotionValue("Anxiety")
        self.assertGreater(anxietyAfterEvent, 10)

        # 时间自然平复不得覆盖事件累积出的焦虑值。
        system.ApplyEmotionDecay(60)
        self.assertEqual(system.GetEmotionValue("Anxiety"), anxietyAfterEvent)

    def test_emotion_threshold_boundaries(self):
        """六种情绪应只根据各自的单一阈值判断触发状态。"""
        thresholds = {
            "Joy": 30,
            "Excite": 40,
            "Anxiety": 25,
            "Fear": 30,
            "Curious": 20,
        }
        for emotion, threshold in thresholds.items():
            system = MarsdogEmotionSystem()
            self.assertFalse(system.IsEmotionTriggered(emotion, threshold - 1))
            self.assertTrue(system.IsEmotionTriggered(emotion, threshold))
            self.assertTrue(system.IsEmotionTriggered(emotion, 100))

        # Calm 的阈值为0，状态值又限制在0-100，因此始终处于触发状态。
        system = MarsdogEmotionSystem()
        self.assertTrue(system.IsEmotionTriggered("Calm", -1))
        self.assertTrue(system.IsEmotionTriggered("Calm", 0))
        self.assertTrue(system.IsEmotionTriggered("Calm", 100))

    def test_emotion_signal_event_emits_on_threshold_entry(self):
        """情绪首次达到阈值时应生成一次精简的 V2 signal event。"""
        system = MarsdogEmotionSystem()

        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=1.0), [])
        system.SetEmotionValue("Joy", 35)
        events = system.GetEmotionSignalEventsValue(timestamp=2.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0],
            {
                "schema_version": "2.0",
                "timestamp": 2.0,
                "event_type": "EMO_JOY_TRIGGERED",
                "emotion": "Joy",
                "value": 35,
                "triggerThreshold": 30,
                "triggerOperator": "gte",
            },
        )
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=3.0), [])

    def test_emotion_signal_retriggers_only_after_leaving_threshold(self):
        """触发后升高不重复发送，退出阈值后再次进入才重新发送。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Joy", 30)
        self.assertEqual(
            len(system.GetEmotionSignalEventsValue(timestamp=1.0)),
            1,
        )

        system.SetEmotionValue("Joy", 100)
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=2.0), [])
        system.SetEmotionValue("Joy", 29)
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=3.0), [])
        system.SetEmotionValue("Joy", 30)
        events = system.GetEmotionSignalEventsValue(timestamp=4.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "EMO_JOY_TRIGGERED")

    def test_dominant_change_and_calm_do_not_emit_extra_events(self):
        """主导情绪变化和始终触发的 Calm 都不得产生额外事件。"""
        system = MarsdogEmotionSystem()
        system.SetEmotionValue("Joy", 30)
        system.SetEmotionValue("Fear", 30)
        initialEvents = system.GetEmotionSignalEventsValue(timestamp=1.0)
        self.assertEqual(len(initialEvents), 2)

        system.SetEmotionValue("Fear", 100)
        system.SetEmotionValue("Calm", 100)

        self.assertEqual(system.GetDominantEmotion(), "Fear")
        self.assertEqual(system.GetEmotionSignalEventsValue(timestamp=2.0), [])


if __name__ == "__main__":
    unittest.main()
