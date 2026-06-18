import unittest

from marsdog_core.config_loader import LoadConfig


class ActionConfigSchemaTest(unittest.TestCase):
    def test_actions_config_has_schema_version_and_random_policy(self):
        """动作配置应声明版本和随机策略。"""
        config = LoadConfig("actions")

        self.assertEqual(config["schemaVersion"], 1)
        self.assertEqual(config["randomPolicy"]["mode"], "sample_without_replacement")

    def test_random_phase_plans_define_phase_order_and_selection(self):
        """随机阶段配置必须声明阶段顺序和抽取数量。"""
        config = LoadConfig("actions")

        for plans in config["actions"].values():
            for plan in plans:
                if "randomStepsByPhase" not in plan:
                    continue

                phaseOrder = plan.get("phaseOrder", [])
                self.assertGreater(len(phaseOrder), 0, plan["name"])
                self.assertEqual(set(phaseOrder), set(plan["randomStepsByPhase"].keys()))
                self.assertEqual(set(phaseOrder), set(plan["randomSelection"].keys()))

                for phase in phaseOrder:
                    self.assertGreaterEqual(plan["randomSelection"][phase]["count"], 1)
                    self.assertGreaterEqual(len(plan["randomStepsByPhase"][phase]), 1)

    def test_priority_thresholds_match_demand_trigger_table(self):
        """行为优先级中的生理需求阈值应与需求表触发阈值一致。"""
        config = LoadConfig("priorities")
        rulesByDemand = {
            rule["demand"]: rule
            for rule in config["priorities"]["rules"]
            if rule.get("source") == "demand" and rule.get("demand") in {
                "Hunger",
                "Bladder",
                "Sleepiness",
                "Cleanliness",
            }
        }

        expectedRules = {
            "Hunger": ("gt", 70),
            "Bladder": ("gt", 75),
            "Sleepiness": ("gt", 65),
            "Cleanliness": ("gt", 70),
        }
        for demand, (operator, threshold) in expectedRules.items():
            self.assertEqual(rulesByDemand[demand]["operator"], operator)
            self.assertEqual(rulesByDemand[demand]["threshold"], threshold)


if __name__ == "__main__":
    unittest.main()
