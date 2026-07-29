import unittest

from marsdog_core import MarsdogNeedSystem


class DemandAPITest(unittest.TestCase):
    def test_get_and_set_demand_value_clamps_range(self):
        """需求写入应统一限制在 0-100。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.SetDemandValue("Hunger", 120))
        self.assertEqual(system.GetDemandValue("Hunger"), 100)
        self.assertTrue(system.SetDemandValue("Hunger", -10))
        self.assertEqual(system.GetDemandValue("Hunger"), 0)

    def test_get_all_demands_returns_copy(self):
        """批量读取需求时不暴露内部 dict。"""
        system = MarsdogNeedSystem()

        demands = system.GetAllDemands()
        demands["Hunger"] = 0

        self.assertNotEqual(system.GetDemandValue("Hunger"), 0)

    def test_is_demand_urgent_uses_config_operator(self):
        """紧急判断应使用配置里的阈值和操作符。"""
        system = MarsdogNeedSystem()

        system.SetDemandValue("Hunger", 71)
        system.SetDemandValue("Energy", 81)

        self.assertTrue(system.IsDemandUrgent("Hunger"))
        self.assertTrue(system.IsDemandUrgent("Energy"))

    def test_get_most_urgent_demand_uses_raw_value_order(self):
        """多个需求触发时按原始值排序，不做紧迫度换算。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 80)
        system.SetDemandValue("Exploration", 90)

        self.assertEqual(system.GetMostUrgentDemand(), "Exploration")

    def test_get_most_urgent_demand_excludes_non_triggered_values(self):
        """原始值较大但未触发的需求不应参与紧迫度比较。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Hunger", 71)
        system.SetDemandValue("Energy", 80)

        self.assertEqual(system.GetMostUrgentDemand(), "Hunger")

        system.SetDemandValue("Energy", 95)
        self.assertEqual(system.GetMostUrgentDemand(), "Energy")

    def test_get_demand_level_value_uses_v2_boundaries(self):
        """全部需求应按 V2 配置计算边界等级，缺少的等级必须跳过。"""
        system = MarsdogNeedSystem()
        cases = {
            "Hunger": {
                69: "NORMAL", 70: "NORMAL", 71: "TRIGGERED",
                89: "TRIGGERED", 90: "TRIGGERED", 91: "OVERFLOW", 100: "OVERFLOW",
            },
            "Bladder": {74: "NORMAL", 75: "NORMAL", 76: "TRIGGERED", 100: "TRIGGERED"},
            "Sleepiness": {
                64: "NORMAL", 65: "NORMAL", 66: "TRIGGERED",
                89: "TRIGGERED", 90: "TRIGGERED", 91: "OVERFLOW", 100: "OVERFLOW",
            },
            "Cleanliness": {69: "NORMAL", 70: "NORMAL", 71: "TRIGGERED", 100: "TRIGGERED"},
            "Energy": {
                79: "NORMAL", 80: "NORMAL", 81: "TRIGGERED",
                89: "TRIGGERED", 90: "TRIGGERED", 91: "OVERFLOW", 100: "OVERFLOW",
            },
            "Social": {
                59: "NORMAL", 60: "NORMAL", 61: "TRIGGERED",
                69: "TRIGGERED", 70: "TRIGGERED", 71: "URGENT",
                84: "URGENT", 85: "URGENT", 86: "OVERFLOW", 100: "OVERFLOW",
            },
            "Exploration": {59: "NORMAL", 60: "NORMAL", 61: "TRIGGERED", 100: "TRIGGERED"},
        }

        for demand, values in cases.items():
            for value, expectedLevel in values.items():
                with self.subTest(demand=demand, value=value):
                    system.SetDemandValue(demand, value)
                    self.assertEqual(system.GetDemandLevelValue(demand)["level"], expectedLevel)

    def test_get_demand_level_value_supports_energy_deficit(self):
        """Energy 应按高充电需求值计算等级。"""
        system = MarsdogNeedSystem()

        system.SetDemandValue("Energy", 80)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "NORMAL")
        system.SetDemandValue("Energy", 81)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "TRIGGERED")
        system.SetDemandValue("Energy", 90)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "TRIGGERED")
        system.SetDemandValue("Energy", 91)
        self.assertEqual(system.GetDemandLevelValue("Energy")["level"], "OVERFLOW")

    def test_demand_signal_events_emit_only_on_level_change(self):
        """需求事件只应在等级变化时输出一次。"""
        system = MarsdogNeedSystem()

        self.assertEqual(system.GetDemandSignalEventsValue(timestamp=1.0), [])

        system.SetDemandValue("Hunger", 71)
        events = system.GetDemandSignalEventsValue(timestamp=2.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["schema_version"], "2.0")
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_TRIGGERED")
        self.assertEqual(events[0]["level"], "TRIGGERED")
        self.assertEqual(events[0]["previousLevel"], "NORMAL")
        self.assertEqual(system.GetDemandSignalEventsValue(timestamp=3.0), [])

        system.SetDemandValue("Hunger", 95)
        events = system.GetDemandSignalEventsValue(timestamp=4.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_OVERFLOW")
        self.assertEqual(events[0]["previousLevel"], "TRIGGERED")

        system.SetDemandValue("Hunger", 50)
        events = system.GetDemandSignalEventsValue(timestamp=5.0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "NEED_HUNGER_RECOVERED")
        self.assertEqual(events[0]["previousLevel"], "OVERFLOW")

    def test_social_signal_events_cover_all_v2_level_transitions(self):
        """Social 进入和退出三段触发区间时都应发布当前等级事件。"""
        system = MarsdogNeedSystem()
        steps = [
            (60, None, None, None),
            (61, "NEED_SOCIAL_TRIGGERED", "NORMAL", "TRIGGERED"),
            (70, None, None, None),
            (71, "NEED_SOCIAL_URGENT", "TRIGGERED", "URGENT"),
            (85, None, None, None),
            (86, "NEED_SOCIAL_OVERFLOW", "URGENT", "OVERFLOW"),
            (85, "NEED_SOCIAL_URGENT", "OVERFLOW", "URGENT"),
            (70, "NEED_SOCIAL_TRIGGERED", "URGENT", "TRIGGERED"),
            (60, "NEED_SOCIAL_RECOVERED", "TRIGGERED", "NORMAL"),
        ]

        for index, (value, eventType, previousLevel, level) in enumerate(steps, start=1):
            system.SetDemandValue("Social", value)
            events = system.GetDemandSignalEventsValue(timestamp=float(index))
            with self.subTest(value=value):
                if eventType is None:
                    self.assertEqual(events, [])
                    continue
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event_type"], eventType)
                self.assertEqual(events[0]["previousLevel"], previousLevel)
                self.assertEqual(events[0]["level"], level)
                self.assertEqual(events[0]["urgentThreshold"], 70)
                self.assertEqual(events[0]["urgentOperator"], "gt")

    def test_v2_config_uses_distinct_trigger_and_urgent_threshold_names(self):
        """V2 配置应统一首次触发字段，并只给 Social 配置中间紧急线。"""
        system = MarsdogNeedSystem()
        configs = system.configs["demands"]

        for demand, config in configs.items():
            with self.subTest(demand=demand):
                self.assertIn("triggerThreshold", config)
                self.assertIn("triggerOperator", config)
        self.assertEqual(configs["Social"]["urgentThreshold"], 70)
        demandsWithoutUrgent = (
            "Hunger", "Bladder", "Sleepiness", "Cleanliness", "Energy", "Exploration",
        )
        for demand in demandsWithoutUrgent:
            with self.subTest(noUrgentDemand=demand):
                self.assertNotIn("urgentThreshold", configs[demand])

    def test_demands_without_overflow_stay_triggered_at_100(self):
        """未配置满溢线的需求达到 100 时仍应保持 TRIGGERED。"""
        system = MarsdogNeedSystem()

        for demand in ("Bladder", "Cleanliness", "Exploration"):
            with self.subTest(demand=demand):
                system.SetDemandValue(demand, 100)
                levelInfo = system.GetDemandLevelValue(demand)
                self.assertEqual(levelInfo["level"], "TRIGGERED")
                self.assertIsNone(levelInfo["overflowThreshold"])
                self.assertIsNone(levelInfo["overflowOperator"])


if __name__ == "__main__":
    unittest.main()
