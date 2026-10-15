"""Trigger classification is derived, local, and independent of priority."""
import unittest
from unittest.mock import patch

from bionic_dog_bt.drive_policy import BehaviorDrive, DIRECT_SOURCES, resolve_drive
from marsdog_behavior import decision_trace
from marsdog_behavior.intent_mapper import BehaviorCandidate


class DrivePolicyTests(unittest.TestCase):
    def test_registered_perception_sources_override_borrowed_state_metadata(self):
        for source in DIRECT_SOURCES:
            with self.subTest(source=source):
                policy = resolve_drive({"source": source, "source_emotion": "Joy"}, "emotional")
                self.assertEqual(policy.drive, BehaviorDrive.PERCEPTION_DIRECT)
                self.assertEqual(policy.state_domain, "")
                self.assertFalse(policy.legacy)

    def test_emotions_and_needs_share_internal_drive_but_keep_distinct_state_owners(self):
        for source in ("emotion", "need"):
            policy = resolve_drive({"source": source}, "external")
            self.assertEqual(policy.drive, BehaviorDrive.INTERNAL_STATE)
            self.assertEqual(policy.state_domain, source)
            self.assertFalse(policy.legacy)

    def test_legacy_need_types_still_gate_missing_or_unknown_sources(self):
        for source in (None, "unregistered_plugin"):
            for need_type, domain in (("emotional", "emotion"), ("physiological", "need"),
                                      ("physiological_urgent", "need"), ("psychological", "need")):
                policy = resolve_drive({"source": source}, need_type)
                self.assertEqual(policy.state_domain, domain)
                self.assertTrue(policy.legacy)

    def test_system_idle_and_unknown_do_not_invent_a_business_drive(self):
        for source in ("system", "idle", "unknown", ""):
            self.assertIsNone(resolve_drive({"source": source, "source_emotion": "Joy"}).drive)

    def test_drive_hints_cannot_override_the_authoritative_source(self):
        policy = resolve_drive({"source": "emotion", "behavior_drive": "perception_direct"})
        self.assertEqual(policy.state_domain, "emotion")

    def test_observation_adds_drive_without_changing_candidate_or_goal_payload(self):
        candidate = BehaviorCandidate(source="audio_reaction", source_emotion="Joy",
                                      behavior_name="expressJoyAlone", priority_level=1)
        before = candidate.to_pool_dict()
        with patch.object(decision_trace, "enabled", return_value=True), \
                patch.object(decision_trace, "observe") as observe:
            decision_trace.emit("candidate_queued", before)
        fields = observe.call_args.args[1]
        self.assertEqual(fields["behavior_drive"], "perception_direct")
        self.assertEqual(fields["state_domain"], "")
        self.assertNotIn("behavior_drive", before["params"])
        self.assertEqual(candidate.to_pool_dict(), before)

    def test_priority_and_template_do_not_change_drive_classification(self):
        for priority in range(7):
            for source, drive in (("visual_direct", BehaviorDrive.PERCEPTION_DIRECT),
                                   ("emotion", BehaviorDrive.INTERNAL_STATE)):
                item = BehaviorCandidate(source=source, behavior_name="same-template",
                                         priority_level=priority).to_pool_dict()
                self.assertEqual(resolve_drive(item["params"], item["need_type"]).drive, drive)
                self.assertEqual(item["priority_level"], priority)


if __name__ == "__main__":
    unittest.main()
