import math
import unittest
from pathlib import Path

from marsdog_core.config_loader import LoadAllConfigs
from marsdog_core.types import (
    ActionResultType,
    ActionType,
    DemandType,
    EmotionType,
    PersonalityParam,
    PersonalityProfileType,
)
from tools.export_emotion_event_catalog import (
    BuildEmotionEventCatalogCsvValue,
    BuildEmotionEventCatalogMarkdownValue,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigContractTest(unittest.TestCase):
    def setUp(self):
        """加载一次项目配置，供每个契约检查使用。"""
        self.configs = LoadAllConfigs(PROJECT_ROOT / "configs")

    def assertFiniteNumber(self, value: object, fieldName: str) -> None:
        """断言配置值是有限数字，并显式拒绝布尔值。"""
        self.assertNotIsInstance(value, bool, fieldName)
        self.assertIsInstance(value, (int, float), fieldName)
        self.assertTrue(math.isfinite(float(value)), fieldName)

    def test_demand_config_matches_registered_types(self):
        """需求配置、动作映射和基础阈值必须引用已注册枚举。"""
        demands = self.configs["demands"]
        expectedDemands = {item.value for item in DemandType}
        self.assertEqual(set(demands), expectedDemands)

        validOperators = {"gt", "gte", "lt", "lte", "eq"}
        for demandName, config in demands.items():
            with self.subTest(demand=demandName):
                self.assertEqual(config.get("range"), [0, 100])
                self.assertIn(config.get("triggerOperator"), validOperators)
                self.assertFiniteNumber(
                    config.get("triggerThreshold"),
                    f"{demandName}.triggerThreshold",
                )

        actionDemandMap = self.configs["demandGlobalRules"]["actionDemandMap"]
        validActions = {item.value for item in ActionType}
        for actionName, demandName in actionDemandMap.items():
            self.assertIn(actionName, validActions)
            self.assertIn(demandName, expectedDemands)

    def test_emotion_config_references_only_registered_emotions(self):
        """情绪类型、阈值和衰减规则必须与六维情绪枚举一致。"""
        emotions = self.configs["emotions"]
        deduplicationWindow = emotions.get("eventDeduplicationWindowSeconds")
        self.assertFiniteNumber(
            deduplicationWindow,
            "emotions.eventDeduplicationWindowSeconds",
        )
        self.assertGreaterEqual(float(deduplicationWindow), 0)
        emotionTypes = emotions["types"]
        expectedEmotions = {item.value for item in EmotionType}
        self.assertEqual(set(emotionTypes), expectedEmotions)
        self.assertEqual(set(emotions["thresholds"]), expectedEmotions)
        self.assertLessEqual(set(emotions["decayRules"]), expectedEmotions)
        for emotionName, config in emotionTypes.items():
            with self.subTest(emotion=emotionName):
                self.assertEqual(config.get("range"), [0, 100])

    def test_emotion_event_rules_are_machine_valid(self):
        """事件映射只允许合法六维情绪、数字增量和受支持倍率条件。"""
        emotions = self.configs["emotions"]
        expectedEmotions = {item.value for item in EmotionType}
        validMultiplierOperators = {"truthy", "eq", "gt", "gte", "lt", "lte"}
        eventRules = emotions["eventRules"]
        self.assertTrue(eventRules)

        for eventName, mapping in eventRules.items():
            with self.subTest(event=eventName):
                self.assertTrue(eventName.startswith("EVT_"))
                deltas = mapping.get("deltas")
                self.assertIsInstance(deltas, dict)
                self.assertTrue(deltas)
                for emotionName, delta in deltas.items():
                    self.assertIn(emotionName, expectedEmotions)
                    self.assertFiniteNumber(delta, f"{eventName}.{emotionName}")

                for rule in mapping.get("metadataMultipliers", []):
                    self.assertIsInstance(rule, dict)
                    self.assertTrue(str(rule.get("key", "")).strip())
                    operator = rule.get("operator", "truthy")
                    self.assertIn(operator, validMultiplierOperators)
                    self.assertFiniteNumber(
                        rule.get("multiplier"),
                        f"{eventName}.multiplier",
                    )
                    self.assertGreater(float(rule["multiplier"]), 0)
                    if operator in {"gt", "gte", "lt", "lte"}:
                        self.assertFiniteNumber(
                            rule.get("value"),
                            f"{eventName}.value",
                        )

    def test_action_result_rules_reference_registered_values(self):
        """行为结果情绪规则必须引用已登记结果类型和情绪。"""
        emotions = self.configs["emotions"]
        expectedResults = {item.value for item in ActionResultType}
        expectedEmotions = {item.value for item in EmotionType}
        rules = emotions["actionResultRules"]
        self.assertEqual(set(rules), expectedResults)
        for resultName, resultRules in rules.items():
            for rule in resultRules:
                with self.subTest(result=resultName, emotion=rule.get("emotion")):
                    self.assertIn(rule.get("emotion"), expectedEmotions)
                    self.assertFiniteNumber(rule.get("min"), f"{resultName}.min")
                    self.assertFiniteNumber(rule.get("max"), f"{resultName}.max")
                    self.assertLessEqual(float(rule["min"]), float(rule["max"]))

    def test_personality_profiles_are_complete(self):
        """性格预设必须覆盖四个正式预设和全部四维参数。"""
        profiles = self.configs["personalityProfiles"]
        expectedProfiles = {
            item.value
            for item in PersonalityProfileType
            if item is not PersonalityProfileType.CUSTOM
        }
        expectedParams = {item.value for item in PersonalityParam}
        self.assertEqual(set(profiles), expectedProfiles)
        for profileName, profile in profiles.items():
            with self.subTest(profile=profileName):
                params = profile.get("params", {})
                self.assertEqual(set(params), expectedParams)
                for paramName, value in params.items():
                    self.assertFiniteNumber(value, f"{profileName}.{paramName}")
                    self.assertGreaterEqual(float(value), 0)
                    self.assertLessEqual(float(value), 100)

    def test_generated_event_catalog_matches_config(self):
        """提交的事件目录必须由当前配置生成且 CSV 可覆盖全部事件。"""
        emotionConfig = self.configs["emotions"]
        expectedMarkdown = BuildEmotionEventCatalogMarkdownValue(emotionConfig)
        catalogPath = PROJECT_ROOT / "docs" / "emotion_event_catalog.md"
        self.assertTrue(catalogPath.exists())
        self.assertEqual(catalogPath.read_text(encoding="utf-8"), expectedMarkdown)

        csvText = BuildEmotionEventCatalogCsvValue(emotionConfig)
        for eventName in emotionConfig["eventRules"]:
            self.assertIn(eventName, csvText)


if __name__ == "__main__":
    unittest.main()
