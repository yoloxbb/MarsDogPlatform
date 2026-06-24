import random
import unittest

from marsdog_core import MarsdogBehaviorSystem


def CompleteCurrentBehaviorTree(system: MarsdogBehaviorSystem) -> None:
    """通过动作成功反馈完成当前行为树。"""
    for _ in range(20):
        command = system.GetCurrentActionCommand()
        if command is None:
            return
        success = system.OnActionFeedback(
            command["commandId"],
            command["concreteAction"],
            "SUCCESS",
        )
        if not success:
            raise AssertionError(f"Failed to complete command: {command}")
    raise AssertionError("Behavior tree did not finish")


class SocialBehaviorTest(unittest.TestCase):
    def test_morning_social_uses_random_range_and_personality_coefficient(self):
        """晨起 Social 应按随机范围乘性格系数。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetPersonalityParam("A", 100)
        system.SetPersonalityParam("E", 50)

        value = system.InitializeMorningSocial()

        self.assertGreaterEqual(value, 36)
        self.assertLessEqual(value, 54)
        self.assertEqual(system.GetDemandValue("Social"), value)

    def test_social_growth_follows_time_windows(self):
        """Social 应按白天、傍晚、夜间规则增长。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Social", 20)

        system.UpdateSocialByTime(9)
        self.assertEqual(system.GetDemandValue("Social"), 22)

        system.UpdateSocialByTime(19)
        self.assertEqual(system.GetDemandValue("Social"), 25)

        system.UpdateSocialByTime(22)
        self.assertEqual(system.GetDemandValue("Social"), 25)

    def test_personality_profiles_and_coefficients(self):
        """性格预设和五种情绪系数应符合公式。"""
        system = MarsdogBehaviorSystem()

        self.assertTrue(system.SetPersonalityProfileValue("GentleCompanion"))
        self.assertEqual(system.GetPersonalityParams(), {"A": 85, "O": 75, "E": 30, "C": 40})
        self.assertEqual(system.GetPersonalityProfileValue(), "GentleCompanion")

        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Joy"), 1.48)
        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Excite"), 0.93)
        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Anxiety"), 1.87)
        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Curious"), 0.708)
        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Calm"), 1.6)

    def test_all_personality_profiles_are_available(self):
        """四种性格预设都应能写入对应参数。"""
        system = MarsdogBehaviorSystem()
        expectedProfiles = {
            "GentleCompanion": {"A": 85, "O": 75, "E": 30, "C": 40},
            "SunnyExplorer": {"A": 90, "O": 80, "E": 95, "C": 70},
            "LoyalGuardian": {"A": 70, "O": 90, "E": 70, "C": 90},
            "ProudIndependent": {"A": 40, "O": 30, "E": 60, "C": 80},
        }

        for profile, params in expectedProfiles.items():
            self.assertTrue(system.SetPersonalityProfileValue(profile))
            self.assertEqual(system.GetPersonalityParams(), params)

    def test_owner_left_home_bonus_is_applied_once_per_state_change(self):
        """重复离家状态不应重复增加 Social。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Social", 20)

        system.OnOwnerPresenceChanged(False)
        system.OnOwnerPresenceChanged(False)

        self.assertEqual(system.GetDemandValue("Social"), 50)
        system.OnOwnerPresenceChanged(True)
        system.OnOwnerPresenceChanged(False)
        self.assertEqual(system.GetDemandValue("Social"), 80)

    def test_owner_interaction_always_runs_and_settles_after_action(self):
        """主人主动互动不受 Social 阈值限制，动作完成后扣减 25。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(
            randomGenerator=random.Random(1),
            timeProvider=lambda: now[0],
        )
        system.SetDemandValue("Social", 40)

        self.assertTrue(system.OnOwnerInteractionEvent({"event": "wakeup"}))
        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetCurrentAction(), "ACTION_SOCIAL_GREET")
        self.assertEqual(system.GetSocialInteractionStatus()["initiator"], "Owner")
        command = system.GetCurrentActionCommand()
        self.assertEqual(command["context"]["initiator"], "Owner")

        CompleteCurrentBehaviorTree(system)

        self.assertEqual(system.GetDemandValue("Social"), 15)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "Completed")

    def test_owner_interaction_events_are_merged_for_ten_seconds(self):
        """10 秒窗口内 wakeup/speech/intent 只应生成一个主人互动事件。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(timeProvider=lambda: now[0])

        self.assertTrue(system.OnOwnerInteractionEvent({"event": "wakeup"}))
        self.assertFalse(system.OnOwnerInteractionEvent({"event": "speech"}))
        now[0] = 109.9
        self.assertFalse(system.OnOwnerInteractionEvent({"event": "intent"}))
        now[0] = 110.0
        self.assertTrue(system.OnOwnerInteractionEvent({"event": "wakeup"}))

    def test_dog_human_interaction_waits_for_response_before_recovery(self):
        """狗主动对人互动应等待回应，再降低 Social 20。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(
            randomGenerator=random.Random(1),
            timeProvider=lambda: now[0],
        )
        system.SetSocialTargetVisibility(True, False)
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        interactionId = system.GetSocialInteractionStatus()["interactionId"]

        CompleteCurrentBehaviorTree(system)

        self.assertEqual(system.GetDemandValue("Social"), 80)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "WaitingResponse")
        self.assertTrue(system.OnSocialInteractionFeedback(interactionId, "RESPONDED", "Human"))
        self.assertEqual(system.GetDemandValue("Social"), 60)
        self.assertFalse(system.OnSocialInteractionFeedback(interactionId, "RESPONDED", "Human"))

    def test_dog_animal_interaction_recovers_fifteen(self):
        """狗主动与动物互动收到回应后应降低 Social 15。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(3))
        system.SetSocialTargetVisibility(False, True)
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)

        status = system.GetSocialInteractionStatus()
        self.assertEqual(status["targetType"], "Animal")
        self.assertIn(
            system.GetCurrentAction(),
            {"ACTION_SOCIAL_GREET", "ACTION_PLAY_INVITE", "ACTION_BOUNDARY_TEST"},
        )
        CompleteCurrentBehaviorTree(system)

        self.assertTrue(
            system.OnSocialInteractionFeedback(status["interactionId"], "RESPONDED", "Animal")
        )
        self.assertEqual(system.GetDemandValue("Social"), 65)

    def test_human_target_has_priority_over_animal(self):
        """同时看到人和动物时应优先选择人类目标。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(2))
        system.SetSocialTargetVisibility(True, True)
        system.SetDemandValue("Social", 80)

        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetSocialInteractionStatus()["targetType"], "Human")
        self.assertIn(
            system.GetCurrentAction(),
            {"ACTION_ATTENTION_SEEK", "ACTION_PLAY_INVITE", "ACTION_RESOURCE_SHARE"},
        )

    def test_no_target_searches_for_owner_first(self):
        """没有目标时应先执行寻找主人动作。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetSocialTargetVisibility(False, False)
        system.SetDemandValue("Social", 80)

        system.Tick(currentTime=9, applyDemandGrowth=False)
        command = system.GetCurrentActionCommand()

        self.assertEqual(system.GetCurrentAction(), "ACTION_ATTENTION_SEEK")
        self.assertEqual(command["concreteAction"], "ACT_SEARCH_FOR_PERSON")

    def test_waiting_response_blocks_duplicate_social_interaction(self):
        """等待回应期间不应再次发起社交会话。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        interactionId = system.GetSocialInteractionStatus()["interactionId"]
        CompleteCurrentBehaviorTree(system)

        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetCurrentAction(), "ACTION_LOAF")
        self.assertEqual(system.GetSocialInteractionStatus()["interactionId"], interactionId)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "WaitingResponse")

    def test_timeout_and_rejection_do_not_change_social_or_emotions(self):
        """超时或拒绝不应改变 Social 和情绪。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(
            randomGenerator=random.Random(1),
            timeProvider=lambda: now[0],
        )
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        CompleteCurrentBehaviorTree(system)
        emotionsBefore = system.GetAllEmotions()

        now[0] = 131.0
        self.assertEqual(system.UpdateSocialInteractionState(), "TimedOut")
        self.assertEqual(system.GetDemandValue("Social"), 80)
        self.assertEqual(system.GetAllEmotions(), emotionsBefore)

        system.Tick(currentTime=9, applyDemandGrowth=False)
        CompleteCurrentBehaviorTree(system)
        secondStatus = system.GetSocialInteractionStatus()
        self.assertTrue(
            system.OnSocialInteractionFeedback(
                secondStatus["interactionId"],
                "REJECTED",
                secondStatus["targetType"],
            )
        )
        self.assertEqual(system.GetDemandValue("Social"), 80)
        self.assertEqual(system.GetAllEmotions(), emotionsBefore)

    def test_late_feedback_is_rejected_without_waiting_for_tick(self):
        """超过截止时间的反馈应由反馈接口直接拒绝。"""
        now = [100.0]
        system = MarsdogBehaviorSystem(
            randomGenerator=random.Random(1),
            timeProvider=lambda: now[0],
        )
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        CompleteCurrentBehaviorTree(system)
        status = system.GetSocialInteractionStatus()

        now[0] = 131.0
        accepted = system.OnSocialInteractionFeedback(
            status["interactionId"],
            "RESPONDED",
            status["targetType"],
        )

        self.assertFalse(accepted)
        self.assertEqual(system.GetDemandValue("Social"), 80)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "TimedOut")

    def test_higher_priority_interrupts_social_without_emotion_change(self):
        """高优先级打断主动社交时应 Social -20，但不修改情绪。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        system.GetCurrentActionCommand()
        emotionsBefore = system.GetAllEmotions()

        system.OnEnvironmentChange("danger", 70)
        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetCurrentAction(), "ACTION_FLEE")
        self.assertEqual(system.GetDemandValue("Social"), 60)
        self.assertEqual(system.GetAllEmotions(), emotionsBefore)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "Interrupted")

    def test_higher_priority_closes_waiting_response_session(self):
        """等待回应期间命中 Lv.0-Lv.3 行为也应关闭社交会话。"""
        system = MarsdogBehaviorSystem(randomGenerator=random.Random(1))
        system.SetDemandValue("Social", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)
        CompleteCurrentBehaviorTree(system)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "WaitingResponse")

        system.SetDemandValue("Hunger", 80)
        system.Tick(currentTime=9, applyDemandGrowth=False)

        self.assertEqual(system.GetCurrentAction(), "ACTION_EAT")
        self.assertEqual(system.GetDemandValue("Social"), 60)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "Interrupted")


if __name__ == "__main__":
    unittest.main()
