import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


def CompleteCurrentBehaviorTree(system: MarsdogBehaviorSystem) -> None:
    """通过成功反馈完成当前行为树。"""
    for _ in range(20):
        command = system.GetCurrentActionCommand()
        if command is None:
            return
        if not system.OnActionFeedback(
            command["commandId"],
            command["concreteAction"],
            "SUCCESS",
        ):
            raise AssertionError(f"Failed to complete command: {command}")
    raise AssertionError("Behavior tree did not finish")


class ExplorationBehaviorTest(unittest.TestCase):
    def test_morning_exploration_uses_k_curious(self):
        """晨起 Exploration 应为随机 10-20 乘 k_curious。"""
        seed = 1
        expectedBase = random.Random(seed).randint(10, 20)
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(seed))

        value = system.InitializeMorningExploration()

        expected = round(expectedBase * system.GetEmotionPersonalityCoefficientValue("Curious"))
        self.assertEqual(value, expected)
        self.assertEqual(system.GetDemandValue("Exploration"), expected)

    def test_exploration_growth_requires_daytime_and_energy_over_fifty(self):
        """只有白天且 Energy > 50 时 Exploration 每 Tick 增加 5。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Exploration", 10)

        system.SetDemandValue("Energy", 51)
        system.UpdateExplorationByTime(9)
        self.assertEqual(system.GetDemandValue("Exploration"), 15)

        system.SetDemandValue("Energy", 50)
        system.UpdateExplorationByTime(9)
        self.assertEqual(system.GetDemandValue("Exploration"), 15)

        system.SetDemandValue("Energy", 100)
        system.UpdateExplorationByTime(22)
        self.assertEqual(system.GetDemandValue("Exploration"), 15)

    def test_exploration_trigger_is_strictly_greater_than_sixty(self):
        """Exploration 等于 60 不触发，大于 60 才触发空间探索。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Exploration", 60)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        self.assertNotEqual(system.GetCurrentAction(), "ACTION_EXPLORE")

        system.SetDemandValue("Exploration", 61)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        self.assertEqual(system.GetCurrentAction(), "ACTION_EXPLORE")

    def test_space_exploration_selects_one_action_and_recovers_fifteen(self):
        """主动空间探索应随机执行一个动作并降低 Exploration 15。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Exploration", 80)

        system.Tick(currentTime=9, applyDemandGrowth=False)
        command = system.GetCurrentActionCommand()

        self.assertEqual(system.GetCurrentAction(), "ACTION_EXPLORE")
        self.assertIn(
            command["concreteAction"],
            {
                "ACT_TROT_AND_LOOK_AROUND",
                "ACT_WALK_SLOWLY_AND_SNIFF_GROUND",
                "ACT_CRAWL_THROUGH_LOW_GAP",
                "ACT_STAND_AND_SCRATCH_HIGH",
                "ACT_SCRATCH_DOOR_OR_FENCE",
                "ACT_FIND_COOL_SPOT_AND_LIE_DOWN",
            },
        )
        self.assertEqual(command["context"]["targetType"], "Space")

        CompleteCurrentBehaviorTree(system)

        self.assertEqual(system.GetDemandValue("Exploration"), 65)
        self.assertEqual(system.GetExplorationContext()["lastResult"], "Completed")

    def test_new_and_old_discovery_recovery_values(self):
        """发现新事物应恢复 20，旧事物恢复 10。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Exploration", 80)

        self.assertTrue(system.ExecuteExploration("New"))
        self.assertEqual(system.GetDemandValue("Exploration"), 60)

        system.SetDemandValue("Exploration", 80)
        self.assertTrue(system.ExecuteExploration("Old"))
        self.assertEqual(system.GetDemandValue("Exploration"), 70)

    def test_detected_target_is_locked_and_repeated_detection_is_ignored(self):
        """同一目标待执行或执行中时不应被持续感知重复覆盖。"""
        system = MarsdogBehaviorSystem()

        self.assertTrue(
            system.OnExplorationTargetDetected(
                "DeliveryBox",
                "box-1",
                "New",
                {"value": 90},
            )
        )
        self.assertFalse(
            system.OnExplorationTargetDetected(
                "DeliveryBox",
                "box-1",
                "Old",
                {"value": 90},
            )
        )

        system.Tick(currentTime=9, applyDemandGrowth=False)
        context = system.GetExplorationContext()

        self.assertEqual(system.GetCurrentAction(), "ACTION_OBJECT_EXPLORE")
        self.assertEqual(context["targetId"], "box-1")
        self.assertEqual(context["discoveryType"], "New")

    def test_new_object_action_recovers_twenty_and_later_becomes_old(self):
        """同一目标首次按新事物结算，完成后再次识别按旧事物结算。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Exploration", 90)

        self.assertTrue(system.OnExplorationTargetDetected("Door", "door-1", metadata={"value": 90}))
        system.Tick(currentTime=9, applyDemandGrowth=False)
        firstCommand = system.GetCurrentActionCommand()
        self.assertIn(
            firstCommand["concreteAction"],
            {
                "ACT_IGNORE_DOOR",
                "ACT_LEAN_AGAINST_DOOR",
                "ACT_LIE_BY_DOOR",
                "ACT_SCRATCH_DOOR",
                "ACT_SNIFF_AROUND_DOOR",
            },
        )
        CompleteCurrentBehaviorTree(system)
        self.assertEqual(system.GetDemandValue("Exploration"), 70)

        self.assertTrue(system.OnExplorationTargetDetected("Door", "door-1", metadata={"value": 90}))
        system.Tick(currentTime=9, applyDemandGrowth=False)
        self.assertEqual(system.GetExplorationContext()["discoveryType"], "Old")
        CompleteCurrentBehaviorTree(system)
        self.assertEqual(system.GetDemandValue("Exploration"), 60)

    def test_specific_object_types_use_their_own_action_pools(self):
        """识别特定物品时应使用对应动作池。"""
        expectedPools = {
            "SlippersOrSocks": {
                "ACT_IGNORE_SLIPPERS_OR_SOCKS",
                "ACT_BITE_SLIPPERS_OR_SOCKS",
                "ACT_POUNCE_ON_SLIPPERS_OR_SOCKS",
                "ACT_CARRY_SLIPPERS_OR_SOCKS_TO_PERSON",
                "ACT_SCRATCH_SLIPPERS_OR_SOCKS_WITH_PAW",
                "ACT_SNIFF_SLIPPERS_OR_SOCKS",
            },
            "TrashCan": {
                "ACT_IGNORE_TRASH_CAN",
                "ACT_RUMMAGE_THROUGH_TRASH_CAN",
                "ACT_SNIFF_TRASH_CAN",
            },
            "DeliveryBox": {
                "ACT_IGNORE_DELIVERY_BOX",
                "ACT_SNIFF_DELIVERY_BOX",
                "ACT_BITE_DELIVERY_BOX",
                "ACT_CARRY_DELIVERY_BOX_TO_PERSON",
                "ACT_SCRATCH_DELIVERY_BOX_WITH_PAW",
            },
            "Tissue": {
                "ACT_IGNORE_TISSUE",
                "ACT_SNIFF_TISSUE",
                "ACT_SCRATCH_TISSUE_WITH_PAW",
                "ACT_CARRY_TISSUE_TO_PERSON",
            },
            "Door": {
                "ACT_IGNORE_DOOR",
                "ACT_LEAN_AGAINST_DOOR",
                "ACT_LIE_BY_DOOR",
                "ACT_SCRATCH_DOOR",
                "ACT_SNIFF_AROUND_DOOR",
            },
        }

        for targetType, actionPool in expectedPools.items():
            system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
            system.state.explorationCurrentTargetType = targetType
            steps = system.GetActionSequence("ACTION_OBJECT_EXPLORE")
            self.assertEqual(len(steps), 1)
            self.assertIn(steps[0], actionPool)

    def test_higher_priority_interrupts_active_exploration(self):
        """高优先级行为打断主动探索时应执行全局 Exploration -20。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Exploration", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        system.GetCurrentActionCommand()

        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetCurrentAction(), "ACTION_EAT")
        self.assertEqual(system.GetDemandValue("Exploration"), 60)
        self.assertEqual(system.GetExplorationContext()["lastResult"], "Interrupted")


if __name__ == "__main__":
    unittest.main()
