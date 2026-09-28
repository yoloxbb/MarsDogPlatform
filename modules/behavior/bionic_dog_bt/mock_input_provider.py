"""Mock input provider: simulates upstream perception/needs modules.

Aligned with ROS2 topic structures:
  - /emotion/state         → EmotionModule (Joy, Excite, Anxiety, Fear, Curious, Calm)
  - /internal_need/state   → NeedModule (Hunger, Bladder, Sleepiness, Cleanliness,
                                         Energy, Social, Exploration)

Each inject_* method:
  1. Updates the corresponding EmotionModule or NeedModule state
  2. Creates an ActiveBehavior candidate

The select() method implements candidate selection when multiple inputs are active,
using the same priority key as the deployed candidate pool, with cooldown awareness.
"""

from __future__ import annotations

import uuid
from typing import Optional

from .datatypes import ActiveBehavior
from .arbitration import priority_key
from .blackboard import Blackboard
from .constants import (
    PRIORITY_LEVELS,
    DEFAULT_IDLE_BEHAVIOR,
    DEFAULT_EMOTION_CONFIG,
    DEFAULT_NEED_CONFIG,
    NEED_LEVEL_NORMAL,
    EMOTION_EVENT_BEHAVIOR_MAP,
    NEED_EVENT_BEHAVIOR_MAP,
    VOICE_EVENT_BEHAVIOR_MAP,
)
from .emotion_module import EmotionModule
from .need_module import NeedModule
from .mock_perception_client import MockPerceptionClient
from .visual_context import (
    select_exploration_context,
    select_hunger_context,
    select_social_animal,
)


class MockInputProvider:
    """Simulates upstream inputs that generate behavior candidates.

    Emotion-triggered injections update EmotionModule so BehaviorRelevanceCondition
    can verify the V2 ``triggered`` flag at execution time.
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

    def inject_excretion(self, value: float = 95.0) -> Optional[ActiveBehavior]:
        """Inject a Bladder event selected from the current need level."""
        return self._inject_need_value("Bladder", value)

    def inject_sleep(self, value: float = 90.0) -> Optional[ActiveBehavior]:
        """Inject a Sleepiness event selected from the current need level."""
        return self._inject_need_value("Sleepiness", value)

    # ── Lv2 External Interaction ─────────────────────────────────────────────

    def inject_owner_call(self, value: float = 85.0) -> ActiveBehavior:
        """Inject a hardware wake event that orients to the sound source."""
        params = {
            "target": "owner",
            "source": "audio_direct",
            "trigger_event": "EVT_VOICE_WAKEUP",
            "semantic_rank": 2,
            "modality_rank": 1,
        }
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

    def inject_touch_head(self, value: float = 70.0) -> ActiveBehavior:
        """Someone touches the dog's head."""
        params = {
            "touch_zone": "head",
            "semantic_rank": 3,
            "modality_rank": 0,
        }
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

    def inject_hunger(self, value: float = 85.0) -> Optional[ActiveBehavior]:
        """Inject a Hunger event selected from the current need level."""
        return self._inject_need_value("Hunger", value)

    def inject_cleanliness(self, value: float = 75.0) -> Optional[ActiveBehavior]:
        """Inject a Cleanliness event selected from the current need level."""
        return self._inject_need_value("Cleanliness", value)

    # ── Lv4 Psychological ────────────────────────────────────────────────────

    def inject_social_need(self, value: float = 75.0) -> Optional[ActiveBehavior]:
        """Inject a Social event selected from the current need level."""
        return self._inject_need_value("Social", value)

    def inject_explore(self, value: float = 70.0) -> Optional[ActiveBehavior]:
        """Inject an Exploration event selected from the current need level."""
        return self._inject_need_value("Exploration", value)

    def inject_energy(self, value: float = 85.0) -> Optional[ActiveBehavior]:
        """Inject an Energy event selected from the current need level."""
        return self._inject_need_value("Energy", value)

    # ── Lv5 EmotionExpression ────────────────────────────────────────────────

    def inject_joy_trigger(self, value: float = 30.0) -> Optional[ActiveBehavior]:
        """Inject the Joy V2 single-threshold event."""
        return self._inject_emotion_value("Joy", value)

    def inject_happy_overflow(self, value: float = 85.0) -> Optional[ActiveBehavior]:
        """Deprecated compatibility alias for :meth:`inject_joy_trigger`."""
        return self.inject_joy_trigger(value)

    def inject_fear(self, value: float = 80.0) -> Optional[ActiveBehavior]:
        """Inject the exact Fear strength event for ``value``."""
        return self._inject_emotion_value("Fear", value)

    def inject_curiosity(self, value: float = 65.0) -> Optional[ActiveBehavior]:
        """Inject the exact Curious strength event for ``value``."""
        return self._inject_emotion_value("Curious", value)

    def inject_emotion_expression(self, value: float = 80.0) -> Optional[ActiveBehavior]:
        """Generic emotion-driven behavior injection.

        Finds the dominant emotion, checks its V2 threshold, and
        delegates to ``inject_emotion_event``.
        """
        dominant = self._emotion_module.get_dominant_emotion()
        if dominant is None:
            return None
        emotion_name, current_val = dominant
        return self._inject_emotion_value(emotion_name, current_val)

    def inject_emotion_event(
        self,
        event_type: str,
        value: float,
    ) -> Optional[ActiveBehavior]:
        """Inject one exact V2 ``EMO_*_TRIGGERED`` event."""
        entry = EMOTION_EVENT_BEHAVIOR_MAP.get(event_type)
        if entry is None:
            return None

        emotion_name = entry["emotion_name"]
        self._emotion_module.update_state(emotion_name, value, True)
        person = self._perception.check_person()
        interactive = bool(person.get("present"))
        visual_route = "human" if interactive else "solo"
        route_entry = entry["routes"][visual_route]
        target = None
        if interactive:
            identity = str(person.get("identity", "unknown"))
            target = {
                "target_type": "human",
                "target_id": "mock-vision:human:1",
                "vision_epoch": "mock-vision",
                "identity": identity,
            }
        params = {
            "source": "emotion",
            "source_emotion": emotion_name,
            "emotion_value": value,
            "level": entry["level"],
            "visual_route": visual_route,
            "visual_resolved": True,
            "interactive": interactive,
            "interaction_mode": "interactive" if interactive else "solo",
            "target": target,
            "target_identity": (
                target.get("identity") if target is not None else None
            ),
            "trigger_event": event_type,
            "variant": entry["variant"],
        }

        b = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name=route_entry["behavior_name"],
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=value, confidence=0.85,
            need_type="emotional",
            interrupt_policy="safe_point",
            timeout_sec=30.0, cooldown_sec=1.0,
            params=params,
            style={"emotion": emotion_name},
        )
        self._add_candidate(b)
        return b

    def _inject_emotion_value(
        self,
        emotion_name: str,
        value: float,
    ) -> Optional[ActiveBehavior]:
        """Convert a mock emotion value to its V2 single-threshold event."""
        config = DEFAULT_EMOTION_CONFIG.get(emotion_name)
        if config is None:
            return None
        if value < config["trigger_threshold"]:
            self._emotion_module.update_state(emotion_name, value, False)
            return None

        return self.inject_emotion_event(
            f"EMO_{emotion_name.upper()}_TRIGGERED",
            value,
        )

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

    # ── Need Event Injection ────────────────────────────────────────────────

    def inject_need_event(
        self,
        event_type: str,
        value: float,
    ) -> Optional[ActiveBehavior]:
        """Inject one exact configured V2 need event."""
        entry = NEED_EVENT_BEHAVIOR_MAP.get(event_type)
        if entry is None:
            return None

        need_name = entry["need_name"]
        self._need_module.set_need(need_name, value)
        current_level = self._need_module.get_level(need_name)
        expected_level = event_type.rsplit("_", 1)[-1]
        if current_level != expected_level:
            return None
        self._need_module.level_events[need_name] = event_type

        visual_route = None
        target = None
        effective_entry = entry
        routes = entry.get("visual_routes", {})
        if need_name == "Hunger":
            context = select_hunger_context(
                self._perception.detect_objects(0.5)
            )
            visual_route = context["route"]
            target = context["target"]
            effective_entry = {**entry, **routes[visual_route]}
        elif need_name == "Social":
            person = self._perception.check_person()
            if person.get("present"):
                visual_route = "human"
                identity = str(person.get("identity", "unknown"))
                target = {
                    "target_type": "human",
                "target_id": "mock-vision:human:1",
                "vision_epoch": "mock-vision",
                    "identity": identity,
                }
            else:
                target = select_social_animal(
                    self._perception.detect_objects(0.5)
                )
                if target is None:
                    return None
                visual_route = "animal"
            effective_entry = {**entry, **routes[visual_route]}
        elif need_name == "Exploration":
            context = select_exploration_context(
                self._perception.detect_objects(0.5)
            )
            visual_route = context["route"]
            target = context["target"]
            effective_entry = {**entry, **routes[visual_route]}

        priority_level = effective_entry["priority_level"]
        timeout_by_level = {
            0: 5.0,
            2: 60.0,
            3: 30.0,
            4: 25.0,
        }
        cooldown_by_level = {
            0: 0.0,
            2: 0.0,
            3: 5.0,
            4: 5.0,
        }
        params = {
            "source": "need",
            "source_need": need_name,
            "trigger_event": event_type,
            "need_value": value,
            "level": expected_level,
            "variant": effective_entry["variant"],
            "sub_priority": effective_entry.get("sub_priority", 0),
        }
        if effective_entry.get("executor_behavior_name"):
            params["executor_behavior_name"] = effective_entry[
                "executor_behavior_name"
            ]
        if visual_route is not None:
            params.update({
                "visual_route": visual_route,
                "target": target,
                "object_category": (
                    target.get("object_category")
                    if isinstance(target, dict)
                    else None
                ),
                "interactive": visual_route in ("human", "animal"),
                "interaction_mode": (
                    "interactive"
                    if visual_route in ("human", "animal")
                    else "solo"
                ),
            })

        behavior = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name=effective_entry["behavior_name"],
            priority_level=priority_level,
            value=value,
            confidence=0.8,
            need_type=effective_entry["need_type"],
            interrupt_policy="safe_point",
            timeout_sec=timeout_by_level[priority_level],
            cooldown_sec=cooldown_by_level[priority_level],
            params=params,
        )
        self._add_candidate(behavior)
        return behavior

    def _inject_need_value(
        self,
        need_name: str,
        value: float,
    ) -> Optional[ActiveBehavior]:
        """Convert a mock need value to its exact configured V2 event."""
        self._need_module.set_need(need_name, value)
        level = self._need_module.get_level(need_name)
        if level == NEED_LEVEL_NORMAL:
            return None
        return self.inject_need_event(
            f"NEED_{need_name.upper()}_{level}",
            value,
        )

    # ── Batch Injection (ROS2 state simulation) ──────────────────────────────

    def inject_emotion_state(self, emotions: dict) -> None:
        """Simulate receiving a full /emotion/state message.

        State updates never generate candidates. Dict values may be either
        numbers or V2 objects containing ``value`` and ``triggered``.
        """
        for name, emotion_info in emotions.items():
            if isinstance(emotion_info, dict):
                value = float(emotion_info["value"])
                triggered = bool(emotion_info["triggered"])
            else:
                value = float(emotion_info)
                threshold = DEFAULT_EMOTION_CONFIG.get(
                    name,
                    {"trigger_threshold": 70.0},
                )["trigger_threshold"]
                triggered = value >= threshold
            self._emotion_module.update_state(name, value, triggered)

    def inject_need_state(self, needs: dict[str, float]) -> None:
        """Simulate receiving a full /internal_need/state message.

        State snapshots update the cache but never create edge candidates.
        """
        for name, value in needs.items():
            self._need_module.set_need(name, value)

    # ── Audio Event Injection (ROS2 /perception/audio_event) ─────────────────

    def inject_event(
        self,
        event_type: str,
        value: float | None = None,
    ) -> Optional[ActiveBehavior]:
        """Inject any supported exact event type."""
        if event_type in VOICE_EVENT_BEHAVIOR_MAP:
            return self.inject_audio_event(
                event_type,
                value if value is not None else 85.0,
            )

        if event_type in NEED_EVENT_BEHAVIOR_MAP:
            if value is None:
                entry = NEED_EVENT_BEHAVIOR_MAP[event_type]
                config = DEFAULT_NEED_CONFIG[entry["need_name"]]
                level = event_type.rsplit("_", 1)[-1]
                threshold_key = {
                    "TRIGGERED": "trigger_threshold",
                    "URGENT": "urgent_threshold",
                    "OVERFLOW": "overflow_threshold",
                }[level]
                value = float(config[threshold_key]) + 1.0
            return self.inject_need_event(event_type, value)

        if event_type in EMOTION_EVENT_BEHAVIOR_MAP:
            if value is None:
                emotion_name = EMOTION_EVENT_BEHAVIOR_MAP[event_type]["emotion_name"]
                value = DEFAULT_EMOTION_CONFIG[emotion_name]["trigger_threshold"]
            return self.inject_emotion_event(event_type, value)

        return None

    def inject_audio_event(
        self,
        event_type: str,
        value: float = 85.0,
    ) -> Optional[ActiveBehavior]:
        """Simulate an event-type-driven /perception/audio_event."""
        behavior_name = VOICE_EVENT_BEHAVIOR_MAP.get(event_type)
        if behavior_name is None:
            return None

        if event_type == "EVT_VOICE_WAKEUP":
            return self.inject_owner_call(value)

        need_gate = {
            "EVT_VOICE_COMMAND_TOILET": ("Bladder", 50.0),
            "EVT_VOICE_COMMAND_CLEAN": ("Cleanliness", 40.0),
            "EVT_VOICE_COMMAND_SLEEP": ("Sleepiness", 50.0),
        }.get(event_type)
        if need_gate is not None:
            need_name, threshold = need_gate
            state = self._need_module.get_need(need_name)
            if state is None or not state.current_value > threshold:
                return None

        if behavior_name == "emergency_stop":
            return self.inject_emergency_stop(value)

        # Strong commands have one-to-one semantic behaviors. They must not
        # collapse back to respond_owner_call/respond_touch_head.
        timeout_by_behavior = {
            "walk_to_random_point": 50.0,
            "play_alone": 0.0,
            "go_out_to_play": 50.0,
            "go_home": 60.0,
            "approach_owner": 10.0,
            "back_up": 6.0,
            "sit_down": 5.0,
            "lie_down": 5.0,
            "stand_up": 5.0,
            "stand_still": 10.0,
            "hold_position": 10.0,
            "wait_in_place": 30.0,
            "come_to_owner": 12.0,
            "follow_owner": 0.0,
            "give_paw": 5.0,
            "high_five": 5.0,
            "roll_over": 6.0,
            "spin_around": 6.0,
            "return_to_owner": 12.0,
            "drop_object": 3.0,
            "quiet": 3.0,
            "barkShortAlert": 60.0,
            "lickPaws": 15.0,
            "sleepOnSide": 120.0,
            "play_dead": 8.0,
            "bring_object": 20.0,
            "fetch_object": 30.0,
        }
        if behavior_name not in timeout_by_behavior:
            return None

        self._perception.set_person_present(True, identity="owner")
        behavior = ActiveBehavior(
            behavior_id=self._gen_id(),
            behavior_name=behavior_name,
            priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
            value=value,
            confidence=0.9,
            need_type="external",
            interrupt_policy="immediate",
            timeout_sec=timeout_by_behavior[behavior_name],
            cooldown_sec=1.0,
            params={
                "trigger_event": event_type,
                "source": "audio_direct",
                "target": "owner",
                "semantic_rank": 1,
                "modality_rank": 1,
                **({
                    "lifecycle_scope": "behavior",
                    "completion_policy": "until_preempted",
                    "cancel_on_voice_idle": False,
                } if behavior_name in {"follow_owner", "play_alone"} else {}),
            },
        )
        self._add_candidate(behavior)
        return behavior

    # ── Candidate Selection ──────────────────────────────────────────────────

    def select(self) -> Optional[ActiveBehavior]:
        """Select the best candidate from accumulated inputs.

        Simulates upstream processing (local value decay, need level recomputation)
        before selection — this represents the time elapsed since the last BT tick
        during which /emotion and /internal_need nodes have been running.

        Rules:
        1. Compare level, semantics, modality, then behavior rank.
        2. Same key: higher value wins.
        3. If no candidates, return idle_look_around.
        4. Clears candidate list after selection.
        """
        # ── Simulate upstream processing between BT ticks ─────────────────
        # The local value decay does not change the authoritative V2
        # ``triggered`` flag. Tests simulate recovery with a state update.
        # The real /internal_need node recalculates levels every 600s.
        # Here we tick both to simulate elapsed time.
        self._emotion_module.tick()
        self._need_module.tick()

        if not self._candidates:
            self.inject_idle()
            self._candidates = [self._candidates[-1]]

        self._candidates.sort(key=lambda b: (
            *priority_key(b.priority_level, b.params), -b.value,
        ))
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
