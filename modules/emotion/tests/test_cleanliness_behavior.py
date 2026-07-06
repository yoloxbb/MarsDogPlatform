import random
import unittest

from marsdog_core import MarsdogNeedSystem


class CleanlinessBehaviorTest(unittest.TestCase):
    def test_initialize_morning_cleanliness_uses_range(self):
        """清洁晨起值应在 5-15 随机范围内。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningCleanliness()

        self.assertTrue(5 <= value <= 15)
        self.assertEqual(system.GetDemandValue("Cleanliness"), value)

    def test_cleanliness_grows_only_in_daytime(self):
        """清洁脏污值白天每 Tick +2，其他时间不增长。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Cleanliness", 10)

        system.UpdateCleanlinessByTime(8)
        self.assertEqual(system.GetDemandValue("Cleanliness"), 12)
        system.UpdateCleanlinessByTime(22)
        self.assertEqual(system.GetDemandValue("Cleanliness"), 12)

    def test_after_eat_increases_cleanliness_need(self):
        """进食后 Cleanliness 增加 20。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Cleanliness", 10)

        self.assertEqual(system.ApplyCleanlinessAfterEat(), 30)

    def test_groom_completed_reduces_cleanliness_need(self):
        """清洁完成应降低 Cleanliness 50。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Cleanliness", 80)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_GROOM", "result_type": "COMPLETED"}))

        self.assertEqual(system.GetDemandValue("Cleanliness"), 30)

    def test_groom_interrupted_reduces_cleanliness_once(self):
        """清洁被打断应按全局规则单次 -20。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Cleanliness", 80)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_GROOM", "result_type": "INTERRUPTED"}))

        self.assertEqual(system.GetDemandValue("Cleanliness"), 60)


if __name__ == "__main__":
    unittest.main()
