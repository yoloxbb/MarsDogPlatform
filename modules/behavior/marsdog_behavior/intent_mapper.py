"""Intent Mapper — event → category → intent → behavior_name pipeline.

Loads event_intent_map.yaml, intent_action_pool.yaml, emotion_behavior_map.yaml,
behavior_categories.yaml, and legacy_behavior_aliases.yaml.

BehaviorCandidate: structured dataclass with sub_priority, intensity, level,
variant, interaction_mode, and target fields.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from bionic_dog_bt.logger import get_logger
from bionic_dog_bt.constants import EMOTION_V2_EVENT_TO_NAME, EMOTION_PRIORITY
from .config_paths import get_config_dir

_log = get_logger("intent_mapper")

AUDIO_EVENTS_FOR_EMOTION_ENGINE = {
    "EVT_VOICE_MASTER_ID", "EVT_VOICE_STRANGER_ID",
    "EVT_VOICE_PRAISE", "EVT_VOICE_SCOLD",
    "EVT_VOICE_HAPPY", "EVT_VOICE_SAD", "EVT_VOICE_NEUTRAL",
}

# ═══════════════════════════════════════════════════════════════════════════
# BehaviorCandidate — structured with all required fields
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorCandidate:
    """Structured behavior candidate with intent metadata."""

    behavior_name: str = ""
    source: str = ""              # audio_direct / need / emotion / idle
    trigger_event: str = ""       # e.g. "EVT_VOICE_COMMAND_SIT", "EMO_JOY_TRIGGERED"
    intent: str = ""              # e.g. "command_sit", "express_joy"

    priority_level: int = 6
    sub_priority: int = 0

    intensity: float | None = None
    level: str | None = None      # need level: TRIGGERED / URGENT / OVERFLOW
    variant: str | None = None    # e.g. "joy", "shallow", "boundary"

    interactive: bool = False
    target_required: bool = False
    target: dict[str, Any] | None = None
    interaction_mode: str = "solo"  # solo / interactive

    params: dict[str, Any] = field(default_factory=dict)
    result_mapping: dict[str, Any] | None = None

    interrupt_policy: str = "safe_point"
    ttl_sec: float = 10.0
    # Optional end-to-end behavior timeout.  Long-running candidates such as
    # waypoint navigation must not inherit the short priority-level default.
    timeout_sec: float | None = None
    confidence: float = 0.8
    source_emotion: str = ""
    source_demand: str = ""
    allow_repeat: bool = False
    emotion_priority: int = 50
    candidate_id: str = field(default_factory=lambda: f"cand_{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=time.time)

    @property
    def dedup_key(self) -> tuple:
        """Composite dedup key: (source, trigger_event, behavior_name, variant, interaction_mode)."""
        return (
            self.source,
            self.trigger_event,
            self.behavior_name,
            self.variant or "",
            self.interaction_mode,
        )

    @property
    def sort_key(self) -> tuple:
        """Sort key: (priority_level, sub_priority, -intensity, -created_at)."""
        return (
            self.priority_level,
            self.sub_priority,
            -(self.intensity or 0.0),
            -self.created_at,
        )

    def to_pool_dict(self) -> dict:
        """Convert to the CandidatePool transport representation.

        All lifecycle fields are preserved so arbitration does not silently
        replace the mapping layer's TTL or interrupt policy with defaults.
        """
        return {
            "behavior_name": self.behavior_name,
            "priority_level": self.priority_level,
            "sub_priority": self.sub_priority,
            "value": self.intensity if self.intensity is not None else 50.0,
            "confidence": self.confidence,
            "need_type": _category_to_need_type(self._category_from_level()),
            "source_emotion": self.source_emotion,
            "dedup_key": self.dedup_key,
            "interrupt_policy": self.interrupt_policy,
            "ttl_sec": self.ttl_sec,
            "candidate_id": self.candidate_id,
            "created_at": self.created_at,
            "params": {
                "schema_version": "2.0",
                "source": self.source,
                "trigger_event": self.trigger_event,
                "intent": self.intent,
                "category": self._category_from_level(),
                "level": self.level,
                "variant": self.variant,
                "interaction_mode": self.interaction_mode,
                "interactive": self.interactive,
                "target": self.target,
                "intensity": self.intensity,
                "source_emotion": self.source_emotion,
                "source_need": self.source_demand,
                "candidate_id": self.candidate_id,
                "sub_priority": self.sub_priority,
                "result_mapping": self.result_mapping,
                **self.params,
            },
            "timeout_sec": (
                self.timeout_sec
                if self.timeout_sec is not None
                else _default_timeout_for_level(self.priority_level)
            ),
            "cooldown_sec": _default_cooldown_for_level(self.priority_level),
            "allow_repeat": self.allow_repeat,
            "emotion_priority": self.emotion_priority,
        }

    def _category_from_level(self) -> str:
        _map = {0: "safety", 1: "external_interaction", 2: "urgent_physiology",
                3: "normal_physiology", 4: "psychological_need",
                5: "emotion_expression", 6: "idle"}
        return _map.get(self.priority_level, "idle")


def _category_to_need_type(category: str) -> str:
    mapping = {
        "safety": "system", "urgent_physiology": "physiological_urgent",
        "external_interaction": "external", "normal_physiology": "physiological",
        "psychological_need": "psychological", "emotion_expression": "emotional",
        "idle": "idle",
    }
    return mapping.get(category, "external")


def _default_timeout_for_level(level: int) -> float:
    defaults = {0: 5.0, 1: 8.0, 2: 60.0, 3: 30.0, 4: 25.0, 5: 30.0, 6: 30.0}
    return defaults.get(level, 30.0)


def _default_cooldown_for_level(level: int) -> float:
    defaults = {0: 0.0, 1: 1.0, 2: 0.0, 3: 5.0, 4: 5.0, 5: 1.0, 6: 0.0}
    return defaults.get(level, 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# IntentMapper
# ═══════════════════════════════════════════════════════════════════════════

class IntentMapper:
    """Maps upstream events to BehaviorCandidates via category + intent pipeline."""

    def __init__(self, config_dir: str = None):
        config_dir = str(get_config_dir(config_dir))

        self._event_intent = self._load(config_dir, "event_intent_map.yaml")
        self._intent_pool = self._load(config_dir, "intent_action_pool.yaml")
        self._categories = self._load(config_dir, "behavior_categories.yaml")
        self._emotion_map = self._load(config_dir, "emotion_behavior_map.yaml")
        self._legacy_aliases = self._load(config_dir, "legacy_behavior_aliases.yaml")

        self._legacy_emotion = self._legacy_aliases.get("legacy_emotion_behavior_aliases", {})
        self._legacy_need = self._legacy_aliases.get("legacy_need_behavior_aliases", {})
        self._all_aliases = {**self._legacy_emotion, **self._legacy_need}

        _log.info("IntentMapper loaded: audio=%d need=%d emotion=%d aliases=%d",
                  len(self._event_intent.get("audio_direct", {})),
                  len(self._event_intent.get("need", {})),
                  len(self._emotion_map.get("emotion_behavior_map", {})),
                  len(self._all_aliases))

    def get_emotion_continuation_config(self) -> dict[str, Any]:
        """Return a copy of the optional sustained-expression policy."""
        value = self._emotion_map.get("emotion_continuation", {})
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _load(config_dir: str, filename: str) -> dict:
        path = Path(config_dir) / filename
        if not path.exists():
            _log.warning("Config not found: %s", path)
            return {}
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}

    # ── Public API ───────────────────────────────────────────────────────

    def map_audio_event(self, event_type: str, data: dict) -> Optional[BehaviorCandidate]:
        """Map an audio_event to a BehaviorCandidate.

        Behavior selection is driven exclusively by the exact ``event_type``
        configured under ``audio_direct``. Other payload fields do not select
        the intent or behavior.
        """
        audio_map = self._event_intent.get("audio_direct", {})
        entry = audio_map.get(event_type)
        if entry is None:
            destination = (
                " → emotion_engine"
                if event_type in AUDIO_EVENTS_FOR_EMOTION_ENGINE
                else ""
            )
            _log.debug("Audio event %s ignored%s", event_type, destination)
            return None

        return self._build_audio_candidate(
            event_type,
            data,
            intent_entry=entry,
        )

    def map_need_event(self, event_type: str, data: dict) -> Optional[BehaviorCandidate]:
        """Map a need signal_event to a BehaviorCandidate via event_intent_map."""
        need_map = self._event_intent.get("need", {})
        entry = need_map.get(event_type)
        if entry is None:
            _log.debug("Need event %s not in event_intent_map", event_type)
            return None

        visual_route = data.get("visual_route")
        routes = entry.get("routes", {})
        if entry.get("visual_required"):
            route_entry = routes.get(visual_route)
            if route_entry is None:
                _log.debug(
                    "Need event %s requires visual route; got %r",
                    event_type,
                    visual_route,
                )
                return None
            effective_entry = {**entry, **route_entry}
        else:
            effective_entry = entry

        intent = effective_entry["intent"]
        behavior_name = (
            effective_entry.get("behavior_name")
            or self._select_behavior(intent)
        )
        if behavior_name is None:
            return None

        demand = data.get("demand", "")
        value = float(data.get("value", 80))
        variant = effective_entry.get("variant")
        level = data.get("level", "")
        target = data.get("target")
        route_params = dict(effective_entry.get("params", {}))
        object_category = (
            target.get("object_category")
            if isinstance(target, dict)
            else None
        )
        interactive = (
            visual_route in ("human", "animal")
            and isinstance(target, dict)
        )

        cand = BehaviorCandidate(
            source="need",
            source_demand=demand,
            trigger_event=event_type,
            intent=intent,
            behavior_name=behavior_name,
            priority_level=self._priority_for(effective_entry["category"]),
            sub_priority=effective_entry.get("sub_priority", 0),
            intensity=value,
            level=level or _level_from_event(event_type),
            variant=variant,
            interactive=interactive,
            target_required=isinstance(target, dict),
            target=target if isinstance(target, dict) else None,
            interaction_mode="interactive" if interactive else "solo",
            # Need work is state-backed, not a transient command.  Keep it in
            # the delayed queue until /internal_need/state reports recovery or
            # a different level, at which point ros_node discards/replaces it.
            ttl_sec=0.0,
            timeout_sec=(
                float(effective_entry["timeout_sec"])
                if effective_entry.get("timeout_sec") is not None
                else None
            ),
            confidence=0.8,
            result_mapping=effective_entry.get(
                "result_mapping",
                self._default_result_mapping(behavior_name),
            ),
            params={
                **route_params,
                "intensity": value,
                "level": level or _level_from_event(event_type),
                "variant": variant,
                "visual_route": visual_route,
                "target": target if isinstance(target, dict) else None,
                "object_category": object_category,
            },
        )
        _log.info("Need candidate: %s → %s → %s (Lv%d sp=%d %s)",
                  event_type, intent, behavior_name,
                  cand.priority_level, cand.sub_priority, variant or "")
        return cand

    def map_emotion_event(
        self,
        event_type: str,
        data: dict,
        interactive: bool = False,
        target: dict = None,
        visual_route: str | None = None,
    ) -> Optional[BehaviorCandidate]:
        """Map an emotion signal_event to a BehaviorCandidate via emotion_behavior_map."""
        em_map = self._emotion_map.get("emotion_behavior_map", {})
        entry = em_map.get(event_type)
        if entry is None:
            _log.debug("Emotion event %s not in emotion_behavior_map", event_type)
            return None

        em_name = _event_to_emotion_name(event_type)
        value = float(data.get("value", 80))

        visual_route = (
            visual_route
            or data.get("visual_route")
            or ("human" if interactive and target else "solo")
        )
        routes = entry.get("routes", {})
        route_entry = routes.get(visual_route)
        if entry.get("visual_required") and route_entry is None:
            _log.debug(
                "Emotion event %s requires visual route; got %r",
                event_type,
                visual_route,
            )
            return None
        effective_entry = {**entry, **(route_entry or {})}

        if visual_route == "human" and not isinstance(target, dict):
            _log.debug("Emotion event %s human route has no target", event_type)
            return None

        interaction_mode = effective_entry.get(
            "interaction_mode",
            "interactive" if visual_route == "human" else "solo",
        )
        route_params = dict(effective_entry.get("params", {}))
        interactive = (
            interaction_mode == "interactive"
            and isinstance(target, dict)
        )

        cand = BehaviorCandidate(
            source="emotion",
            source_emotion=em_name,
            trigger_event=event_type,
            intent=effective_entry["intent"],
            behavior_name=effective_entry["behavior_name"],
            priority_level=effective_entry["priority_level"],
            sub_priority=effective_entry.get("sub_priority", 0),
            intensity=value,
            level=effective_entry.get("level"),
            variant=effective_entry.get("variant"),
            interactive=interactive,
            target_required=interactive,
            target=target if interaction_mode == "interactive" else None,
            interaction_mode=interaction_mode,
            ttl_sec=10.0,
            confidence=0.85,
            allow_repeat=bool(effective_entry.get("allow_repeat", False)),
            emotion_priority=EMOTION_PRIORITY.get(em_name, 50),
            interrupt_policy="immediate",
            result_mapping=effective_entry.get("result_mapping"),
            params={
                **route_params,
                "emotion": em_name,
                "intensity": value,
                "level": effective_entry.get("level"),
                "variant": effective_entry.get("variant"),
                "visual_route": visual_route,
                "visual_resolved": True,
                "interaction_mode": interaction_mode,
                "interactive": interactive,
                "target": target if interaction_mode == "interactive" else None,
                "target_identity": (
                    target.get("identity", target.get("target_id", "unknown"))
                    if interactive
                    else None
                ),
            },
        )
        _log.info("Emotion candidate: %s → %s → %s (Lv%d %s %s)",
                  event_type, effective_entry["intent"],
                  effective_entry["behavior_name"], cand.priority_level,
                  interaction_mode, effective_entry.get("variant", ""))
        return cand

    def map_visual_event(self, event_type: str, data: dict) -> None:
        """Visual events MUST NOT generate behavior candidates."""
        return None

    def resolve_alias(self, behavior_name: str) -> str:
        """Resolve a legacy behavior name to its new semantic name."""
        return self._all_aliases.get(behavior_name, behavior_name)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_audio_candidate(self, event_type: str, data: dict,
                               intent_entry: dict) -> Optional[BehaviorCandidate]:
        intent = intent_entry.get("intent", "")
        if not intent:
            return None

        behavior_name = self._select_behavior(intent)
        if behavior_name is None:
            return None

        confidence = float(
            data.get("intent_confidence", data.get("wake_confidence", 0.8))
        )

        # Target fields are metadata only; event_type determines the behavior.
        target_track_id = data.get("target_track_id")
        target_identity = data.get("target_identity")
        target = None
        if target_track_id is not None or target_identity:
            target = {
                "target_type": "human",
                "target_id": target_identity or "unknown",
                "track_id": target_track_id,
            }

        params = {
            **intent_entry.get("params", {}),
            "asr_text": data.get("asr_text", ""),
            "intent_confidence": confidence,
            "target_track_id": target_track_id,
            "target_identity": target_identity,
        }
        if params.get("use_wake_angle") is True:
            try:
                wake_angle_deg = float(data["wake_angle"])
            except (KeyError, TypeError, ValueError):
                _log.warning(
                    "Rejecting %s: missing/invalid wake_angle",
                    event_type,
                )
                return None
            if not math.isfinite(wake_angle_deg):
                _log.warning(
                    "Rejecting %s: non-finite wake_angle=%r",
                    event_type,
                    data.get("wake_angle"),
                )
                return None

            header = data.get("header")
            wake_frame_id = (
                str(header.get("frame_id", "")).strip()
                if isinstance(header, dict)
                else ""
            )
            if not wake_frame_id:
                _log.warning(
                    "Rejecting %s: missing header.frame_id for wake_angle",
                    event_type,
                )
                return None
            params.update({
                "wake_angle_deg": wake_angle_deg,
                "wake_confidence": confidence,
                "wake_frame_id": wake_frame_id,
            })

        cand = BehaviorCandidate(
            source="audio_direct",
            trigger_event=event_type,
            intent=intent,
            behavior_name=behavior_name,
            priority_level=self._priority_for(intent_entry["category"]),
            sub_priority=intent_entry.get("sub_priority", 0),
            intensity=min(confidence * 100, 100.0),
            confidence=confidence,
            ttl_sec=8.0,
            interrupt_policy="immediate",
            interactive=target is not None,
            target=target,
            interaction_mode="interactive" if target else "solo",
            result_mapping=None,
            params=params,
        )
        _log.info("Audio candidate: %s → %s → %s (Lv%d sp=%d)",
                  event_type, intent, behavior_name,
                  cand.priority_level, cand.sub_priority)
        return cand

    def _select_behavior(self, intent: str, interactive: bool = False) -> Optional[str]:
        pool = self._intent_pool.get(intent, {})
        candidates = pool.get("candidates", [])
        if not candidates:
            return None
        return random.choice(candidates)

    def _priority_for(self, category: str) -> int:
        cats = self._categories.get("categories", {})
        return int(cats.get(category, {}).get("priority_level", 6))

    def _default_result_mapping(self, behavior_name: str) -> dict | None:
        """Return result_mapping for known demand behaviors."""
        mapping = {
            "eatNormally": {"action_type": "ACTION_EAT", "demand_type": "Hunger"},
            "eatExcitedly": {"action_type": "ACTION_EAT", "demand_type": "Hunger"},
            "seekFood": {
                "action_type": "ACTION_FOOD_SEEK",
                "demand_type": "Hunger",
            },
            "seekFoodUrgently": {
                "action_type": "ACTION_FOOD_SEEK",
                "demand_type": "Hunger",
            },
            "barkShortAlert": {
                "action_type": "ACTION_DEFECATE",
                "demand_type": "Bladder",
            },
            "defecate": {"action_type": "ACTION_DEFECATE", "demand_type": "Bladder"},
            "sleepOnSide": {
                "action_type": "ACTION_SLEEP",
                "demand_type": "Sleepiness",
            },
            "lickPaws": {
                "action_type": "ACTION_GROOM",
                "demand_type": "Cleanliness",
            },
            "cleanSelf": {"action_type": "ACTION_GROOM", "demand_type": "Cleanliness"},
            "sleepNow": {"action_type": "ACTION_SLEEP", "demand_type": "Sleepiness"},
            "restInPlace": {
                "action_type": "ACTION_RECHARGE",
                "demand_type": "Energy",
            },
            "recharge": {"action_type": "ACTION_RECHARGE", "demand_type": "Energy"},
            "seekHumanInteraction": {
                "action_type": "ACTION_ATTENTION_SEEK",
                "demand_type": "Social",
            },
            "seekInteraction": {
                "action_type": "ACTION_ATTENTION_SEEK",
                "demand_type": "Social",
            },
            "inviteHumanToPlay": {
                "action_type": "ACTION_PLAY_INVITE",
                "demand_type": "Social",
            },
            "exploreRoom": {
                "action_type": "ACTION_SPACE_EXPLORE",
                "demand_type": "Exploration",
            },
            "inspectObject": {
                "action_type": "ACTION_OBJECT_EXPLORE",
                "demand_type": "Exploration",
            },
            **{
                behavior_name: {
                    "action_type": "ACTION_OBJECT_EXPLORE",
                    "demand_type": "Exploration",
                }
                for behavior_name in (
                    "inspectFamiliarPlayItem",
                    "inspectTrashCan",
                    "inspectDeliveryBox",
                    "inspectTissuePaper",
                    "inspectDoor",
                    "inspectDogFood",
                )
            },
        }
        return mapping.get(behavior_name)


def _level_from_event(event_type: str) -> str:
    if "OVERFLOW" in event_type:
        return "OVERFLOW"
    if "URGENT" in event_type:
        return "URGENT"
    if "TRIGGERED" in event_type:
        return "TRIGGERED"
    return ""


def _event_to_emotion_name(event_type: str) -> str:
    return EMOTION_V2_EVENT_TO_NAME.get(event_type, "")


def get_emotion_name_from_event(event_type: str) -> str:
    return _event_to_emotion_name(event_type)
