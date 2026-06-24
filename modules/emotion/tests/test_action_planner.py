import unittest

from marsdog_core import MarsdogBehaviorSystem


class ActionPlannerTest(unittest.TestCase):
    def test_hunger_over_70_uses_normal_eat_sequence(self):
        """饥渴值大于 70 时应展开随机组合的正常进食流程。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 80)
        steps = system.actionPlanner.GetConcreteActions("ACTION_EAT")
        prepareSteps = {"ACT_SNIFF_BOWL_EDGE", "ACT_PAW_AT_BOWL", "ACT_SIT_OR_LIE_BY_BOWL"}
        eatSteps = {
            "ACT_LICK_FOOD",
            "ACT_CHEW_OR_CARRY_FOOD",
            "ACT_SCRATCH_FOOD",
            "ACT_LICK_LIPS_AND_SWALLOW",
        }
        interactionSteps = {
            "ACT_TURN_HEAD_AND_WIPE_MOUTH",
            "ACT_PAUSE_AND_LOOK_AT_OWNER",
            "ACT_CHASE_ROLLING_FOOD",
            "ACT_CHANGE_POSTURE",
            "ACT_GROWL_WHILE_EATING",
            "ACT_BURP",
        }
        finishSteps = {
            "ACT_LICK_LIPS_OR_NOSE",
            "ACT_SHAKE_HEAD",
            "ACT_WALK_AWAY_OR_LIE_DOWN",
            "ACT_SNIFF_GROUND_FOR_CRUMBS",
        }

        self.assertEqual(steps[0], "ACT_RUN_TO_BOWL")
        self.assertEqual(len(steps), 5)
        self.assertIn(steps[1], prepareSteps)
        self.assertIn(steps[2], eatSteps)
        self.assertIn(steps[3], interactionSteps)
        self.assertIn(steps[4], finishSteps)

    def test_hunger_over_90_uses_excited_eat_sequence(self):
        """饥渴值大于 90 时应优先展开激动进食动作。"""
        system = MarsdogBehaviorSystem()

        system.SetDemandValue("Hunger", 95)
        steps = system.actionPlanner.GetConcreteActions("ACTION_EAT")

        self.assertEqual(steps, ["ACT_RUN_TO_BOWL", "ACT_FAST_LICK_AND_SWALLOW"])

    def test_unknown_plan_returns_top_level_action(self):
        """未配置具体动作的顶层行为应原样返回。"""
        system = MarsdogBehaviorSystem()

        self.assertEqual(system.actionPlanner.GetConcreteActions("ACTION_SLEEP"), ["ACTION_SLEEP"])

    def test_action_planner_can_build_behavior_tree(self):
        """动作规划器应能为顶层行为构建行为树。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Hunger", 80)

        runner = system.actionPlanner.BuildBehaviorTree("ACTION_EAT")
        status = runner.Tick()

        self.assertEqual(status.value, "RUNNING")
        self.assertEqual(runner.GetCurrentConcreteAction(), "ACT_RUN_TO_BOWL")

    def test_social_context_selects_human_and_animal_action_branches(self):
        """社交动作树应根据锁定的目标类型选择对应动作池。"""
        system = MarsdogBehaviorSystem()
        system.state.socialInteractionTargetType = "Human"
        system.state.socialInteractionTargetVisible = True
        humanSteps = system.GetActionSequence("ACTION_PLAY_INVITE")

        system.state.socialInteractionTargetType = "Animal"
        animalSteps = system.GetActionSequence("ACTION_PLAY_INVITE")

        self.assertEqual(len(humanSteps), 1)
        self.assertIn(
            humanSteps[0],
            {
                "ACT_PLAY_BOW",
                "ACT_SHAKE_TOY_WITH_MOUTH",
                "ACT_RUN_IN_CIRCLES_OR_ZOOMIES",
                "ACT_NIP_GENTLY_AT_PANTS_OR_HAND",
                "ACT_PLACE_PAW_ON_KNEE",
            },
        )
        self.assertEqual(len(animalSteps), 1)
        self.assertIn(
            animalSteps[0],
            {
                "ACT_PLAY_BOW",
                "ACT_CARRY_AND_SHAKE_OBJECT",
                "ACT_POUNCE_GENTLY",
                "ACT_RUN_IN_CIRCLES_OR_CHASE",
                "ACT_PAW_GENTLY_AT_OTHER",
            },
        )


if __name__ == "__main__":
    unittest.main()
