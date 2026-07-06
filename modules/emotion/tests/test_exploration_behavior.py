import random
import unittest

from marsdog_core import MarsdogNeedSystem


class ExplorationBehaviorTest(unittest.TestCase):
    def test_initialize_morning_exploration_uses_curious_coefficient(self):
        """Exploration 晨起值应乘 k_curious。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(1))

        value = system.InitializeMorningExploration()

        self.assertTrue(10 <= value <= 20)
        self.assertEqual(system.GetDemandValue("Exploration"), value)

    def test_exploration_grows_when_daytime_and_energy_enough(self):
        """白天且 Energy > 50 时 Exploration 每 Tick +5。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 10)
        system.SetDemandValue("Energy", 60)

        system.UpdateExplorationByTime(10)
        self.assertEqual(system.GetDemandValue("Exploration"), 15)

        system.SetDemandValue("Energy", 40)
        system.UpdateExplorationByTime(10)
        self.assertEqual(system.GetDemandValue("Exploration"), 15)

    def test_exploration_target_detected_posts_new_object_event(self):
        """发现新目标时应记录探索上下文并入队 NewObject。"""
        system = MarsdogNeedSystem()

        accepted = system.OnExplorationTargetDetected("DeliveryBox", "box-1")

        self.assertTrue(accepted)
        self.assertEqual(system.state.pendingEvents[-1].eventTag, "NewObject")
        context = system.GetExplorationContext()
        self.assertEqual(context["pendingTargetType"], "DeliveryBox")
        self.assertEqual(context["pendingDiscoveryType"], "New")

    def test_duplicate_exploration_target_is_ignored_while_pending(self):
        """同一待探索目标重复出现时不应重复入队。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.OnExplorationTargetDetected("DeliveryBox", "box-1"))
        self.assertFalse(system.OnExplorationTargetDetected("DeliveryBox", "box-1"))

    def test_execute_exploration_reduces_value_and_marks_known_target(self):
        """探索成功应按发现类型降低 Exploration，并把目标记为已知。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 80)
        system.OnExplorationTargetDetected("DeliveryBox", "box-1")
        system.StartExplorationForDecision("ACTION_OBJECT_EXPLORE")

        self.assertTrue(system.ExecuteExploration("New"))

        self.assertEqual(system.GetDemandValue("Exploration"), 60)
        self.assertIn("box-1", system.state.explorationKnownTargetIds)

    def test_behavior_result_event_explore_completed(self):
        """行为组探索完成结果应按 discoveryType 结算。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 80)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_EXPLORE",
                    "result_type": "COMPLETED",
                    "metadata": {"discoveryType": "Completed"},
                }
            )
        )

        self.assertEqual(system.GetDemandValue("Exploration"), 65)

    def test_exploration_interrupted_reduces_value_once(self):
        """探索被打断应按全局规则单次 -20。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 80)

        self.assertTrue(system.OnBehaviorResultEvent({"action_type": "ACTION_EXPLORE", "result_type": "INTERRUPTED"}))

        self.assertEqual(system.GetDemandValue("Exploration"), 60)


if __name__ == "__main__":
    unittest.main()
