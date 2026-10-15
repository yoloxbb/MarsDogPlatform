"""Voice policy runs on plain state and narrow ports, with no ROS shell."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from marsdog_behavior.voice_engagement_coordinator import (
    VoiceEngagementCoordinator, VoiceEngagementPorts, VoiceEngagementState,
)
from marsdog_behavior.voice_interaction_session import (
    VoiceInteractionSession, ORIENTING, ACQUIRING_TARGET, APPROACHING, WAITING, CLOSED,
)


def target():
    return {"target_type": "human", "target_id": "vision-1:human:7",
            "vision_epoch": "vision-1", "identity_state": "unknown"}


class VoiceCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.session = VoiceInteractionSession("voice-1", 1, hold_token="lease-1")
        self.session.metadata.update(wake_id="wake-1", wake_speaker_id="owner-1",
                                     wake_speaker_role="owner", wake_speaker_status="matched")
        self.state = VoiceEngagementState(session=self.session, generation=1,
                                          config={"acquire_timeout_sec": 2})
        self.ports = VoiceEngagementPorts(
            lease=NS(hold=Mock(return_value=True), release=Mock(return_value=True)),
            targets=NS(request_wake_speaker=Mock()),
            candidates=NS(add=Mock(return_value=True), discard_session=Mock(return_value=1),
                          discard_where=Mock(return_value=1)),
            execution=NS(discard_pending_interaction=Mock(return_value=True),
                         cancel_current_interaction=Mock(return_value=None)),
            emotions=NS(defer=Mock(), resume=Mock()),
            publish_attention=Mock(), build_approach_candidate=Mock(return_value={"candidate": 1}),
            logger=NS(info=Mock(), warn=Mock()),
        )
        self.coordinator = VoiceEngagementCoordinator(
            self.state, self.ports, monotonic=lambda: self.now)

    def finish_orientation(self):
        active = NS(behavior_name="respond_owner_call",
                    params={"interaction_id": "voice-1", "wake_id": "wake-1"})
        self.coordinator.handle_voice_behavior_terminal(active, NS(status="SUCCESS"))

    def test_owner_orientation_acquire_approach_and_wait(self):
        self.coordinator.request_voice_hold(self.session)
        held = self.ports.lease.hold.call_args.kwargs["callback"]
        held({"ok": True})
        self.assertTrue(self.session.hold_active)
        self.finish_orientation()
        self.assertEqual(self.session.phase, ACQUIRING_TARGET)
        callback = self.ports.targets.request_wake_speaker.call_args.args[0]
        callback(target())
        self.assertEqual(self.session.phase, APPROACHING)
        self.ports.candidates.add.assert_called_once_with({"candidate": 1})
        self.coordinator.handle_voice_behavior_terminal(
            NS(behavior_name="approach_voice_caller", params={"interaction_id": "voice-1", "wake_id": "wake-1"}),
            NS(status="SUCCESS", reason="arrived"))
        self.assertEqual(self.session.phase, WAITING)
        self.assertEqual(self.state.attention_interaction_id, "voice-1")
        self.ports.lease.release.assert_called_once_with("voice-1", "lease-1", reset_idle_timer=True)
        self.assertTrue(self.ports.publish_attention.call_args.args[0])

    def test_stranger_waits_without_visual_motion_query(self):
        self.session.metadata.update(wake_speaker_role="stranger", wake_speaker_status="unknown")
        self.finish_orientation()
        self.assertEqual(self.session.phase, WAITING)
        self.ports.targets.request_wake_speaker.assert_not_called()
        self.ports.candidates.add.assert_not_called()
        self.assertFalse(self.ports.publish_attention.call_args.args[0])

    def test_query_timeout_invalidates_late_callback_before_waiting(self):
        self.coordinator.request_wake_speaker(self.session)
        callback = self.ports.targets.request_wake_speaker.call_args.args[0]
        self.now = 12
        self.coordinator.expire_wake_target_query_if_due()
        self.assertEqual(self.session.phase, WAITING)
        self.assertEqual(self.state.generation, 2)
        callback(target())
        self.ports.candidates.add.assert_not_called()

    def test_replaced_session_cannot_receive_old_visual_target(self):
        self.coordinator.request_wake_speaker(self.session)
        callback = self.ports.targets.request_wake_speaker.call_args.args[0]
        replacement = VoiceInteractionSession("voice-2", 2)
        self.state.session = replacement
        callback(target())
        self.assertEqual(replacement.phase, ORIENTING)
        self.ports.candidates.add.assert_not_called()

    def test_late_successful_hold_is_released_after_command_consumes_turn(self):
        self.coordinator.request_voice_hold(self.session)
        held = self.ports.lease.hold.call_args.kwargs["callback"]
        self.coordinator.consume_voice_session_turn(self.session, "voice_command")
        self.assertEqual(self.session.hold_token, "")
        held({"ok": True})
        self.assertFalse(self.session.hold_active)
        self.assertEqual(self.ports.lease.release.call_count, 2)
        self.ports.lease.release.assert_called_with("voice-1", "lease-1", reset_idle_timer=False)

    def test_identity_conflict_rejects_approach(self):
        self.coordinator.request_wake_speaker(self.session)
        callback = self.ports.targets.request_wake_speaker.call_args.args[0]
        callback({**target(), "identity_state": "confirmed_known", "identity": "different-owner"})
        self.assertEqual(self.session.phase, WAITING)
        self.ports.candidates.add.assert_not_called()

    def test_close_session_requests_execution_cancel_and_preserves_scope(self):
        self.coordinator.close_voice_session("wrong-session", reason="idle")
        self.assertEqual(self.session.phase, ORIENTING)
        self.coordinator.close_voice_session("voice-1", reason="idle")
        self.assertEqual(self.session.phase, CLOSED)
        self.ports.candidates.discard_session.assert_called_once_with("voice-1")
        self.ports.execution.discard_pending_interaction.assert_called_once_with("voice-1")
        self.ports.execution.cancel_current_interaction.assert_called_once_with(
            "voice-1", reason="voice_session_closed:idle")
        self.ports.emotions.resume.assert_called_once()


if __name__ == "__main__":
    unittest.main()
