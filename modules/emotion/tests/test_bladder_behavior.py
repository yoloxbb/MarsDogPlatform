import random
import unittest

from marsdog_core import MarsdogNeedSystem


class BladderBehaviorTest(unittest.TestCase):
    def test_initialize_morning_bladder_uses_range(self):
        """排泄晨起值应在 20-30 随机范围内。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningBladder()

        self.assertTrue(20 <= value <= 30)
        self.assertEqual(system.GetDemandValue("Bladder"), value)

    def test_bladder_grows_only_in_daytime(self):
        """排泄值白天每 Tick +3，其他时间不增长。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Bladder", 30)

        system.UpdateBladderByTime(8)
        self.assertEqual(system.GetDemandValue("Bladder"), 33)
        system.UpdateBladderByTime(22)
        self.assertEqual(system.GetDemandValue("Bladder"), 33)

    def test_apply_bladder_after_eat_uses_hunger_before_eat(self):
        """进食后排泄加成应按进食前 Hunger 区间判断。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Bladder", 0)

        self.assertEqual(system.ApplyBladderAfterEat(95), 25)
        system.SetDemandValue("Bladder", 0)
        self.assertEqual(system.ApplyBladderAfterEat(80), 20)
        system.SetDemandValue("Bladder", 0)
        self.assertEqual(system.ApplyBladderAfterEat(60), 0)

    def test_defecate_completed_resets_bladder(self):
        """排泄完成应把 Bladder 归零。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Bladder", 90)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_DEFECATE", "result_type": "COMPLETED"}))

        self.assertEqual(system.GetDemandValue("Bladder"), 0)

    def test_defecate_interrupted_uses_bladder_specific_delta(self):
        """排泄被中断应按 Bladder 配置单次 -40。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Bladder", 90)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_DEFECATE", "result_type": "INTERRUPTED"}))

        self.assertEqual(system.GetDemandValue("Bladder"), 50)


if __name__ == "__main__":
    unittest.main()
