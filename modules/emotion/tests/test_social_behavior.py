import random
import unittest

from marsdog_core import MarsdogNeedSystem


class SocialBehaviorTest(unittest.TestCase):
    def test_initialize_morning_social_uses_personality_coefficient(self):
        """Social 晨起值应乘 k_social，默认人格下等于随机基础值。"""
        system = MarsdogNeedSystem(randomGenerator=random.Random(1))

        value = system.InitializeMorningSocial()

        self.assertTrue(20 <= value <= 30)
        self.assertEqual(system.GetDemandValue("Social"), value)

    def test_social_grows_by_time_window(self):
        """Social 白天 +2，傍晚 +3，夜间不增长。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Social", 20)

        system.UpdateSocialByTime(10)
        self.assertEqual(system.GetDemandValue("Social"), 22)
        system.UpdateSocialByTime(19)
        self.assertEqual(system.GetDemandValue("Social"), 25)
        system.UpdateSocialByTime(23)
        self.assertEqual(system.GetDemandValue("Social"), 25)

    def test_owner_left_home_adds_social_once_until_present_again(self):
        """明确主人离家事件单次增加 Social，重复离家不重复加。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Social", 20)

        system.OnOwnerPresenceChanged(False)
        system.OnOwnerPresenceChanged(False)
        self.assertEqual(system.GetDemandValue("Social"), 50)

        system.OnOwnerPresenceChanged(True)
        system.OnOwnerPresenceChanged(False)
        self.assertEqual(system.GetDemandValue("Social"), 80)

    def test_social_completed_result_updates_by_outcome(self):
        """行为组社交完成结果按 socialOutcome 结算 Social。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Social", 80)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_ATTENTION_SEEK",
                    "result_type": "COMPLETED",
                    "metadata": {"socialOutcome": "DogHumanResponded"},
                }
            )
        )
        self.assertEqual(system.GetDemandValue("Social"), 60)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_SOCIAL_GREET",
                    "result_type": "COMPLETED",
                    "metadata": {"socialOutcome": "DogAnimalResponded"},
                }
            )
        )
        self.assertEqual(system.GetDemandValue("Social"), 45)

    def test_rejected_social_result_does_not_change_value(self):
        """狗主动互动被拒绝或超时时不降低 Social。"""
        system = MarsdogNeedSystem()
        system.SetDemandValue("Social", 80)

        self.assertTrue(
            system.OnBehaviorResultEvent(
                {
                    "action_type": "ACTION_PLAY_INVITE",
                    "result_type": "COMPLETED",
                    "metadata": {"socialOutcome": "Rejected"},
                }
            )
        )

        self.assertEqual(system.GetDemandValue("Social"), 80)

    def test_social_interaction_waits_for_feedback_before_recovery(self):
        """狗主动社交会话应等待匹配反馈后才降低 Social。"""
        now = [100.0]
        system = MarsdogNeedSystem(timeProvider=lambda: now[0])
        system.SetDemandValue("Social", 80)

        self.assertTrue(system.StartSocialInteractionForDecision("ACTION_PLAY_INVITE", "demand"))
        interactionId = system.GetSocialInteractionStatus()["interactionId"]
        self.assertTrue(system.ExecuteSocialInteraction())
        self.assertEqual(system.GetDemandValue("Social"), 80)

        self.assertTrue(system.OnSocialInteractionFeedback(interactionId, "RESPONDED", "Human"))

        self.assertEqual(system.GetDemandValue("Social"), 60)
        self.assertEqual(system.GetSocialInteractionStatus()["state"], "Completed")

    def test_social_feedback_timeout_does_not_recover(self):
        """等待回应超时后不降低 Social。"""
        now = [100.0]
        system = MarsdogNeedSystem(timeProvider=lambda: now[0])
        system.SetDemandValue("Social", 80)

        system.StartSocialInteractionForDecision("ACTION_PLAY_INVITE", "demand")
        system.ExecuteSocialInteraction()
        now[0] = 131.0

        self.assertEqual(system.UpdateSocialInteractionState(), "TimedOut")
        self.assertEqual(system.GetDemandValue("Social"), 80)

    def test_personality_profiles_and_coefficients(self):
        """四维性格预设应影响社交和情绪系数计算。"""
        system = MarsdogNeedSystem()

        self.assertTrue(system.SetPersonalityProfileValue("SunnyExplorer"))

        self.assertEqual(system.GetPersonalityProfileValue(), "SunnyExplorer")
        self.assertAlmostEqual(system.GetSocialPersonalityCoefficientValue(), 1.82)
        self.assertAlmostEqual(system.GetEmotionPersonalityCoefficientValue("Fear"), 0.6)


if __name__ == "__main__":
    unittest.main()
