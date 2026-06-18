import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


class BladderBehaviorTest(unittest.TestCase):
    def test_initialize_morning_bladder_uses_random_range(self):
        """晨起排泄值应落在 20-30。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(3))

        value = system.InitializeMorningBladder()

        self.assertGreaterEqual(value, 20)
        self.assertLessEqual(value, 30)
        self.assertEqual(system.GetDemandValue("Bladder"), value)

    def test_daytime_tick_increases_bladder_by_three(self):
        """白天每 10 分钟 Tick 应让 Bladder 增加 3。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 30)

        system.UpdateNaturalDemandsByTime(currentTime=8)

        self.assertEqual(system.GetDemandValue("Bladder"), 33)

    def test_night_tick_does_not_increase_bladder(self):
        """其他时间 Tick 不增加 Bladder。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 30)

        system.UpdateNaturalDemandsByTime(currentTime=22)

        self.assertEqual(system.GetDemandValue("Bladder"), 30)

    def test_excited_eat_adds_twenty_five_to_bladder(self):
        """Hunger 大于 90 的进食应让 Bladder 增加 25。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 95)
        system.SetDemandValue("Bladder", 10)

        system.ExecuteEat("普通粮", 1, "吃满时长")

        self.assertEqual(system.GetDemandValue("Bladder"), 35)

    def test_normal_eat_adds_twenty_to_bladder(self):
        """Hunger 大于 70 的进食应让 Bladder 增加 20。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Bladder", 10)

        system.ExecuteEat("普通粮", 1, "吃满时长")

        self.assertEqual(system.GetDemandValue("Bladder"), 30)

    def test_bladder_gt_75_triggers_defecate_by_priority_table(self):
        """按优先级表，Bladder > 75 应触发排泄。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 76)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_DEFECATE")

    def test_bladder_equal_75_does_not_trigger_defecate(self):
        """Bladder 等于 75 时尚未超过触发阈值。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 75)

        system.Tick(currentTime=22)

        self.assertNotEqual(system.GetCurrentAction(), "ACTION_DEFECATE")

    def test_bladder_priority_beats_hunger_priority(self):
        """Lv.1 排泄应优先于 Lv.3 饥渴。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Bladder", 76)
        system.SetDemandValue("Hunger", 95)

        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_DEFECATE")

    def test_defecate_behavior_tree_randomly_selects_one_action_per_phase(self):
        """ACTION_DEFECATE 行为树每个阶段应只随机抽 1 个动作。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Bladder", 76)
        steps = system.GetActionSequence("ACTION_DEFECATE")

        self.assertEqual(len(steps), 3)
        self.assertIn(
            steps[0],
            {
                "ACT_SNIFF_AND_CIRCLE",
                "ACT_SCRATCH_GROUND",
                "ACT_SQUAT_TO_PEE",
                "ACT_SQUAT_TO_POOP",
            },
        )
        self.assertIn(
            steps[1],
            {
                "ACT_HESITATE",
                "ACT_TENSE_BODY",
                "ACT_TAIL_MOVEMENT",
                "ACT_SLIGHT_TREMOR",
                "ACT_LOWER_HEAD_OR_TURN",
            },
        )
        self.assertIn(
            steps[2],
            {
                "ACT_STAND_UP_WITH_HIND_LEGS",
                "ACT_SCRATCH_SOIL_OR_GROUND",
                "ACT_SNIFF_EXCREMENT",
                "ACT_WALK_AWAY_OR_SHAKE_HEAD",
            },
        )

    def test_defecate_behavior_tree_success_resets_bladder(self):
        """ACTION_DEFECATE 行为树成功后应将 Bladder 置 0。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Bladder", 90)
        system.Tick(currentTime=22)

        finalStatus = ""
        for _ in range(20):
            finalStatus = system.TickCurrentBehaviorTree()
            currentAction = system.GetCurrentConcreteAction()
            if currentAction:
                system.MarkCurrentConcreteActionDone()
            if finalStatus == "SUCCESS":
                break

        self.assertEqual(finalStatus, "SUCCESS")
        self.assertEqual(system.GetDemandValue("Bladder"), 0)

    def test_interrupted_defecate_reduces_bladder_by_forty(self):
        """排泄被 Lv.0 打断时应按排泄规则 Bladder -= 40。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Bladder", 90)
        system.Tick(currentTime=22)
        system.TickCurrentBehaviorTree()

        system.OnEnvironmentChange("danger", 70)
        system.Tick(currentTime=22)

        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")
        self.assertEqual(system.GetDemandValue("Bladder"), 50)
        self.assertGreaterEqual(system.GetEmotionValue("Anxiety"), 3)


if __name__ == "__main__":
    unittest.main()
