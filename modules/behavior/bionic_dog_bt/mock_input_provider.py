"""Mock input provider: simulates upstream perception/needs modules.

Aligned with ROS2 topic structures:
  - /emotion/state         → EmotionModule (Joy, Excite, Anxiety, Fear, Curious, Calm)
  - /internal_need/state   → NeedModule (Hunger, Bladder, Sleepiness, Cleanliness,
                                         Energy, Social, Exploration)

Each inject_* method:
  1. Updates the corresponding EmotionModule or NeedModule state
  2. Creates an ActiveBehavior candidate

The select() method implements candidate selection when multiple inputs are active,
prioritizing by level then value, with cooldown awareness.
"""

from __future__ import annotations

import uuid
from typing import Optional

from .datatypes import ActiveBehavior
from .blackboard import Blackboard
from .constants import PRIORITY_LEVELS, DEFAULT_IDLE_BEHAVIOR, COMMAND_BEHAVIOR_MAP
from .emotion_module import EmotionModule
from .need_module import NeedModule
from .mock_perception_client import MockPerceptionClient


class MockInputProvider:
    """Simulates upstream inputs that generate behavior candidates.

    Emotion-triggered injections update EmotionModule so BehaviorRelevanceCondition
    can verify the emotion is still overflowing at execution time.
    Need-triggered injections update NeedModule for the same purpose.
    """

    def __init__(self, blackboard: Blackboard, emotion_module: EmotionModule,
                 need_module: NeedModule, perception_client: MockPerceptionClient):
        self._blackboard = blackboard
        self._emotion_module = emotion_module
        self._need_module = need_module
        self._perception = perception_client
        self._candidates: list[ActiveBehavior] = []

    # ── Lv0 System ───────────────────────────────────────────────────────────

    def inject_danger(self, value: float = 100.0) -> ActiveBehavior:
        """Danger detected in environment (system-level)."""
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="avoid_danger",
            priority_level=PRIORITY_LEVELS["SYSTEM"],
            value=value, confidence=0.95,
            need_type="survival",
            interrupt_policy="immediate",
            timeout_sec=5.0, cooldown_sec=1.0,
            params={"danger_type": "obstacle"},
        )
        self._add_candidate(b)
        return b

    def inject_emergency_stop(self, value: float = 100.0) -> ActiveBehavior:
        """Emergency stop triggered (system-level)."""
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="emergency_stop",
            priority_level=PRIORITY_LEVELS["SYSTEM"],
            value=value, confidence=1.0,
            need_type="system",
            interrupt_policy="immediate",
            timeout_sec=5.0, cooldown_sec=0.0,
        )
        self._add_candidate(b)
        return b

    # ── Lv1 PhysioUrgent ─────────────────────────────────────────────────────

    def inject_excretion(self, value: float = 95.0) -> ActiveBehavior:
        """Bladder overflow → excretion_request (ROS2 Bladder > 90)."""
        self._need_module.set_need("Bladder", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="excretion_request",
            priority_level=PRIORITY_LEVELS["PHYSIO_URGENT"],
            value=value, confidence=0.95,
            need_type="physiological_urgent",
            interrupt_policy="safe_point",
            timeout_sec=60.0, cooldown_sec=0.0,
        )
        self._add_candidate(b)
        return b

    def inject_sleep(self, value: float = 90.0) -> ActiveBehavior:
        """Sleepiness overflow → sleep_request (ROS2 Sleepiness > 90)."""
        self._need_module.set_need("Sleepiness", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="sleep_request",
            priority_level=PRIORITY_LEVELS["PHYSIO_URGENT"],
            value=value, confidence=0.9,
            need_type="physiological_urgent",
            interrupt_policy="safe_point",
            timeout_sec=120.0, cooldown_sec=0.0,
        )
        self._add_candidate(b)
        return b

    # ── Lv2 External Interaction ─────────────────────────────────────────────

    def inject_owner_call(self, value: float = 85.0, command_id: str = None) -> ActiveBehavior:
        """Owner calls the dog by name (external event or voice command)."""
        params = {"target": "owner"}
        if command_id:
            params["command_id"] = command_id
            params["source"] = "audio_command"
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="respond_owner_call",
            priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
            value=value, confidence=0.9,
            need_type="external",
            interrupt_policy="immediate",
            timeout_sec=8.0, cooldown_sec=2.0,
            params=params,
            style={"emotion": "Joy"},
        )
        self._add_candidate(b)
        return b

    def inject_touch_head(self, value: float = 70.0, command_id: str = None) -> ActiveBehavior:
        """Someone touches the dog's head (external event or voice command)."""
        params = {"touch_zone": "head"}
        if command_id:
            params["command_id"] = command_id
            params["source"] = "audio_command"
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="respond_touch_head",
            priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
            value=value, confidence=0.85,
            need_type="external",
            interrupt_policy="immediate",
            timeout_sec=5.0, cooldown_sec=1.0,
            params=params,
        )
        self._add_candidate(b)
        return b

    # ── Lv3 PhysioNormal ─────────────────────────────────────────────────────

    def inject_hunger(self, value: float = 85.0) -> ActiveBehavior:
        """Hunger triggered → seek_food_or_water (ROS2 Hunger > 70)."""
        self._need_module.set_need("Hunger", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="seek_food_or_water",
            priority_level=PRIORITY_LEVELS["PHYSIO_NORMAL"],
            value=value, confidence=0.8,
            need_type="physiological",
            interrupt_policy="safe_point",
            timeout_sec=30.0, cooldown_sec=5.0,
        )
        self._add_candidate(b)
        return b

    def inject_cleanliness(self, value: float = 75.0) -> ActiveBehavior:
        """Cleanliness triggered → clean_self (ROS2 Cleanliness > 70)."""
        self._need_module.set_need("Cleanliness", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="clean_self",
            priority_level=PRIORITY_LEVELS["PHYSIO_NORMAL"],
            value=value, confidence=0.7,
            need_type="physiological",
            interrupt_policy="safe_point",
            timeout_sec=15.0, cooldown_sec=3.0,
        )
        self._add_candidate(b)
        return b

    # ── Lv4 Psychological ────────────────────────────────────────────────────

    def inject_social_need(self, value: float = 75.0) -> ActiveBehavior:
        """Social need triggered → seek_social_interaction (ROS2 Social > 60)."""
        self._need_module.set_need("Social", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="seek_social_interaction",
            priority_level=PRIORITY_LEVELS["PSYCHOLOGICAL"],
            value=value, confidence=0.75,
            need_type="psychological",
            interrupt_policy="immediate",
            timeout_sec=20.0, cooldown_sec=5.0,
        )
        self._add_candidate(b)
        return b

    def inject_explore(self, value: float = 70.0) -> ActiveBehavior:
        """Exploration need triggered → explore_environment (ROS2 Exploration > 60)."""
        self._need_module.set_need("Exploration", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="explore_environment",
            priority_level=PRIORITY_LEVELS["PSYCHOLOGICAL"],
            value=value, confidence=0.7,
            need_type="psychological",
            interrupt_policy="immediate",
            timeout_sec=25.0, cooldown_sec=3.0,
        )
        self._add_candidate(b)
        return b

    # ── Lv5 EmotionExpression ────────────────────────────────────────────────

    def inject_happy_overflow(self, value: float = 85.0, command_id: str = None) -> ActiveBehavior:
        """Joy overflow → express_happy.

        If triggered by voice command (CMD_PRAISE/CMD_COMFORT/CMD_ENCOUR),
        there is an interacting person. If triggered by emotion overflow,
        check_person() at execution time determines interactive vs solo mode.
        """
        self._emotion_module.set_emotion("Joy", value)
        params = {}
        if command_id:
            params["command_id"] = command_id
            params["source"] = "audio_command"
            # Voice command implies person is present
            self._perception.set_person_present(True, identity="owner")
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="express_happy",
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=value, confidence=0.85,
            need_type="emotional",
            interrupt_policy="immediate",
            timeout_sec=5.0, cooldown_sec=1.0,
            params=params,
            style={"emotion": "Joy"},
        )
        self._add_candidate(b)
        return b

    def inject_fear(self, value: float = 80.0) -> ActiveBehavior:
        """Fear overflow → express_fear (ROS2 Fear > 60, Fear HIGH zone)."""
        self._emotion_module.set_emotion("Fear", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="express_fear",
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=value, confidence=0.8,
            need_type="emotional",
            interrupt_policy="safe_point",
            timeout_sec=8.0, cooldown_sec=2.0,
        )
        self._add_candidate(b)
        return b

    def inject_curiosity(self, value: float = 65.0) -> ActiveBehavior:
        """Curious overflow → express_curiosity (ROS2 Curious > 50, Curious HIGH zone)."""
        self._emotion_module.set_emotion("Curious", value)
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name="express_curiosity",
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=value, confidence=0.7,
            need_type="emotional",
            interrupt_policy="immediate",
            timeout_sec=4.0, cooldown_sec=1.0,
        )
        self._add_candidate(b)
        return b

    # ── Lv6 Idle ─────────────────────────────────────────────────────────────

    def inject_idle(self) -> ActiveBehavior:
        """Generate default idle behavior."""
        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name=DEFAULT_IDLE_BEHAVIOR,
            priority_level=PRIORITY_LEVELS["IDLE"],
            value=30.0, confidence=1.0,
            need_type="idle",
            interrupt_policy="immediate",
            timeout_sec=10.0, cooldown_sec=0.0,
        )
        self._add_candidate(b)
        return b

    # ── Batch Injection (ROS2 state simulation) ──────────────────────────────

    def inject_emotion_state(self, emotions: dict[str, float]) -> None:
        """Simulate receiving a full /emotion/state message.

        Sets all provided emotions and generates candidates for any
        that are overflowing.
        """
        for name, value in emotions.items():
            self._emotion_module.set_emotion(name, value)
            # Check if overflowing and generate appropriate candidate
            if name == "Joy" and value >= 70:
                self.inject_happy_overflow(value)
            elif name == "Fear" and value >= 60:
                self.inject_fear(value)
            elif name == "Curious" and value >= 50:
                self.inject_curiosity(value)

    def inject_need_state(self, needs: dict[str, float]) -> None:
        """Simulate receiving a full /internal_need/state message.

        Sets all provided needs and generates candidates for any
        that are at TRIGGERED or OVERFLOW level.
        """
        for name, value in needs.items():
            self._need_module.set_need(name, value)
            # Check level and generate appropriate candidate
            level = self._need_module.get_level(name)
            if level in ("TRIGGERED", "OVERFLOW"):
                if name == "Hunger":
                    self.inject_hunger(value)
                elif name == "Bladder":
                    self.inject_excretion(value)
                elif name == "Sleepiness":
                    self.inject_sleep(value)
                elif name == "Cleanliness":
                    self.inject_cleanliness(value)
                elif name == "Social":
                    self.inject_social_need(value)
                elif name == "Exploration":
                    self.inject_explore(value)

    # ── Audio Event Injection (ROS2 /perception/audio_event) ─────────────────

    def inject_audio_command(self, command_id: str,
                             value: float = 85.0) -> Optional[ActiveBehavior]:
        """Simulate receiving EVT_VOICE_COMMAND_KNOWN from /perception/audio_event.

        Maps command_id to the appropriate behavior via COMMAND_BEHAVIOR_MAP.
        Returns the created ActiveBehavior, or None if command is unknown.
        """
        behavior_name = COMMAND_BEHAVIOR_MAP.get(command_id)
        if behavior_name is None:
            return None

        # Route to the appropriate inject method with command context
        if behavior_name == "respond_owner_call":
            return self.inject_owner_call(value, command_id=command_id)
        elif behavior_name == "respond_touch_head":
            return self.inject_touch_head(value, command_id=command_id)
        elif behavior_name == "emergency_stop":
            return self.inject_emergency_stop(value)
        elif behavior_name == "express_happy":
            return self.inject_happy_overflow(value, command_id=command_id)
        return None

    # ── Candidate Selection ──────────────────────────────────────────────────

    def select(self) -> Optional[ActiveBehavior]:
        """Select the best candidate from accumulated inputs.

        Simulates upstream processing (emotion decay, need level recomputation)
        before selection — this represents the time elapsed since the last BT tick
        during which /emotion and /internal_need nodes have been running.

        Rules:
        1. Lower priority_level wins (higher priority).
        2. Same level: higher value wins.
        3. If no candidates, return idle_look_around.
        4. Clears candidate list after selection.
        """
        # ── Simulate upstream processing between BT ticks ─────────────────
        # The real /emotion node decays emotions every 1s.
        # The real /internal_need node recalculates levels every 600s.
        # Here we tick both to simulate elapsed time.
        self._emotion_module.tick()
        self._need_module.tick()

        if not self._candidates:
            self.inject_idle()
            self._candidates = [self._candidates[-1]]

        # Sort by: priority_level ascending, then value descending
        self._candidates.sort(key=lambda b: (b.priority_level, -b.value))
        best = self._candidates[0]

        # If best is in cooldown, try next candidates
        for candidate in self._candidates:
            if not self._blackboard.is_in_cooldown(candidate.behavior_name):
                best = candidate
                break

        self._candidates.clear()
        return best

    def clear_candidates(self) -> None:
        """Clear all pending candidates."""
        self._candidates.clear()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _add_candidate(self, behavior: ActiveBehavior) -> None:
        self._candidates.append(behavior)

    @staticmethod
    def _gen_id() -> str:
        return f"bhv_{uuid.uuid4().hex[:12]}"
