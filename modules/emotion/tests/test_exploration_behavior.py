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

    def test_execute_exploration_reduces_value_by_completed_rule(self):
        """探索成功应统一按 Completed 规则降低 Exploration。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 80)

        self.assertTrue(system.ExecuteExploration("New"))

        self.assertEqual(system.GetDemandValue("Exploration"), 65)

    def test_behavior_result_event_explore_completed(self):
        """探索完成结果应忽略 discoveryType 并统一按 Completed 结算。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Exploration", 80)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_EXPLORE",
                    "result_type": "COMPLETED",
                    "metadata": {"discoveryType": "New"},
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
