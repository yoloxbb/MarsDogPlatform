import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class EmotionAPITest(unittest.TestCase):
    def test_set_and_delta_emotion_clamps_range(self):
        """情绪写入和增量变化应限制在 0-100。"""
        system = MarsdogBehaviorSystem()

        self.assertTrue(system.SetEmotionValue("Joy", 95))
        self.assertTrue(system.ApplyEmotionDelta("Joy", 20))
        self.assertEqual(system.GetEmotionValue("Joy"), 100)

    def test_emotion_changed_callback_is_called(self):
        """情绪变化时应触发回调。"""
        system = MarsdogBehaviorSystem()
        changes = []

        system.OnEmotionChanged(lambda name, old, new: changes.append((name, old, new)))
        system.SetEmotionValue("Anxiety", 10)

        self.assertEqual(changes, [("Anxiety", 0, 10)])

    def test_get_dominant_emotion(self):
        """主导情绪应返回当前值最高的情绪。"""
        system = MarsdogBehaviorSystem()

        system.SetEmotionValue("Curious", 70)

        self.assertEqual(system.GetDominantEmotion(), "Curious")

    def test_apply_action_result_emotion(self):
        """行为结果应按配置范围改变情绪。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))

        self.assertTrue(system.ApplyActionResultEmotion("DemandUnsatisfied"))

        self.assertGreaterEqual(system.GetEmotionValue("Anxiety"), 5)
        self.assertLessEqual(system.GetEmotionValue("Anxiety"), 15)


if __name__ == "__main__":
    unittest.main()
