"""Intent Mapper — event → category → intent → behavior_name pipeline.

Loads event_intent_map.yaml, intent_action_pool.yaml, emotion_behavior_map.yaml,
behavior_categories.yaml, and legacy_behavior_aliases.yaml.  Audio reactions
are one-shot external interactions; they reuse emotion behavior templates
without becoming state-backed emotion candidates.

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
from .audio_contract import _VOICE_SLOT_KEYS, validate_audio_contract

_log = get_logger("intent_mapper")

AUDIO_EVENTS_NOT_FOR_TREE = {
    "EVT_VOICE_MASTER_ID", "EVT_VOICE_FOLK_ID",
    "EVT_VOICE_UNMASTER_ID", "EVT_VOICE_STRANGER_ID",
    "EVT_VOICE_CALL_NAME", "EVT_VOICE_COMMAND_CALL_NAME",
    "EVT_VOICE_PRAISE", "EVT_VOICE_SCOLD",
    "EVT_VOICE_COMFORT", "EVT_VOICE_PLAY_INTERACTION",
    "EVT_VOICE_POSITIVE_EMOTION", "EVT_VOICE_NEGATIVE_EMOTION",
    "EVT_VOICE_STATUS_CARE", "EVT_VOICE_COMMAND_KNOWN",
    "EVT_VOICE_COMMAND_UNKNOWN", "EVT_VOICE_HAPPY",
    "EVT_VOICE_SAD", "EVT_VOICE_NEUTRAL",
}

_EMOTION_NAME_TO_EVENT = {
    name: event_type
    for event_type, name in EMOTION_V2_EVENT_TO_NAME.items()
}


# ═══════════════════════════════════════════════════════════════════════════
# BehaviorCandidate — structured with all required fields
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorCandidate:
    """Structured behavior candidate with intent metadata."""

    behavior_name: str = ""
    source: str = ""              # audio_direct / audio_reaction / need / emotion / idle
    trigger_event: str = ""       # e.g. "EVT_VOICE_COMMAND_SIT", "EMO_JOY_TRIGGERED"
    intent: str = ""              # e.g. "command_sit", "express_joy"

    priority_level: int = 6
    sub_priority: int = 0
    semantic_rank: int = 3
    modality_rank: int = 3

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
    cooldown_sec: float | None = None
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
        """Sort key shared with queued and running priority comparison."""
        return (
            self.priority_level,
            self.semantic_rank,
            self.modality_rank,
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
            "semantic_rank": self.semantic_rank,
            "modality_rank": self.modality_rank,
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
                "semantic_rank": self.semantic_rank,
                "modality_rank": self.modality_rank,
                "result_mapping": self.result_mapping,
                **self.params,
            },
            "timeout_sec": (
                self.timeout_sec
                if self.timeout_sec is not None
                else _default_timeout_for_level(self.priority_level)
            ),
            "cooldown_sec": (
                self.cooldown_sec
                if self.cooldown_sec is not None
                else _default_cooldown_for_level(self.priority_level)
            ),
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

        _log.info("IntentMapper loaded: audio=%d reactions=%d visual=%d need=%d emotion=%d aliases=%d",
                  len(self._event_intent.get("audio_direct", {})),
                  len(self._event_intent.get("audio_reaction", {})),
                  len(self._event_intent.get("visual_direct", {})),
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
            contract = (
                " (non-Tree contract)"
                if event_type in AUDIO_EVENTS_NOT_FOR_TREE
                else ""
            )
            _log.debug("Audio event %s ignored%s", event_type, contract)
            return None

        voice_slots = self._validate_audio_contract(
            event_type,
            data,
            intent_entry=entry,
        )
        if voice_slots is None:
            return None

        return self._build_audio_candidate(
            event_type,
            data,
            intent_entry=entry,
            voice_slots=voice_slots,
        )

    def validate_audio_reaction_event(
        self,
        event_type: str,
        data: dict,
    ) -> bool:
        """Validate an exact one-shot vocabulary reaction contract."""
        return self._validated_audio_reaction(event_type, data) is not None

    def map_audio_reaction(
        self,
        event_type: str,
        data: dict,
        *,
        visual_route: str = "solo",
        target: dict | None = None,
        active_voice_session: bool = False,
    ) -> Optional[BehaviorCandidate]:
        """Map PRAISE/SCOLD into one external-interaction reaction.

        The selected expression reuses the emotion behavior catalog, but the
        candidate remains ``source=audio_reaction`` at Lv1 and never mutates or
        continues the authoritative emotion state.
        """
        validated = self._validated_audio_reaction(event_type, data)
        if validated is None:
            return None
        entry, voice_slots = validated

        reactions = entry.get("reactions", [])
        names: list[str] = []
        weights: list[float] = []
        if not isinstance(reactions, list):
            _log.error("Audio reaction %s has malformed reactions", event_type)
            return None
        for reaction in reactions:
            if not isinstance(reaction, dict):
                return None
            emotion_name = str(reaction.get("emotion", "")).strip()
            try:
                weight = float(reaction.get("weight", 1.0))
            except (TypeError, ValueError):
                return None
            if (
                not emotion_name
                or emotion_name not in _EMOTION_NAME_TO_EVENT
                or not math.isfinite(weight)
                or weight <= 0.0
            ):
                _log.error(
                    "Audio reaction %s has invalid emotion/weight",
                    event_type,
                )
                return None
            names.append(emotion_name)
            weights.append(weight)
        if not names:
            _log.error("Audio reaction %s has no reactions", event_type)
            return None

        emotion_name = random.choices(names, weights=weights, k=1)[0]
        emotion_event = _EMOTION_NAME_TO_EVENT[emotion_name]
        emotion_entry = self._emotion_map.get("emotion_behavior_map", {}).get(
            emotion_event
        )
        if not isinstance(emotion_entry, dict):
            _log.error(
                "Audio reaction %s references unmapped emotion %s",
                event_type,
                emotion_name,
            )
            return None

        visual_route = "human" if visual_route == "human" else "solo"
        route_entry = emotion_entry.get("routes", {}).get(visual_route)
        if not isinstance(route_entry, dict):
            return None
        in_place = active_voice_session and visual_route == "human"
        behavior_key = (
            "voice_waiting_behavior_name" if in_place else "behavior_name"
        )
        behavior_name = str(route_entry.get(behavior_key, "")).strip()
        if not behavior_name:
            _log.warning(
                "Audio reaction %s has no %s route for %s",
                event_type,
                behavior_key,
                visual_route,
            )
            return None
        if visual_route == "human" and not isinstance(target, dict):
            return None

        interaction_id = str(data.get("interaction_id", "")).strip()
        utterance_id = str(data.get("utterance_id", "")).strip()
        interactive = visual_route == "human"
        candidate = BehaviorCandidate(
            source="audio_reaction",
            source_emotion=emotion_name,
            trigger_event=event_type,
            intent=str(entry.get("intent", "")),
            behavior_name=behavior_name,
            priority_level=self._priority_for(str(entry["category"])),
            sub_priority=int(entry.get("sub_priority", 1)),
            semantic_rank=3,
            modality_rank=1,
            intensity=80.0,
            variant=str(emotion_entry.get("variant", "")) or None,
            interactive=interactive,
            target_required=interactive,
            target=target if interactive else None,
            interaction_mode="interactive" if interactive else "solo",
            ttl_sec=float(entry.get("ttl_sec", 5.0)),
            timeout_sec=float(entry.get("timeout_sec", 8.0)),
            cooldown_sec=float(entry.get("cooldown_sec", 2.0)),
            confidence=0.85,
            allow_repeat=False,
            emotion_priority=EMOTION_PRIORITY.get(emotion_name, 50),
            interrupt_policy=str(entry.get("interrupt_policy", "immediate")),
            result_mapping=emotion_entry.get("result_mapping"),
            params={
                "emotion": emotion_name,
                "social_trigger": event_type,
                "interaction_id": interaction_id,
                "utterance_id": utterance_id,
                "audio_event_key": "%s:%s:%s" % (
                    interaction_id,
                    utterance_id,
                    event_type,
                ),
                "session_role": "voice_social_reaction",
                "session_preempt_rank": 0,
                "interaction_variant": (
                    "voice_social_reaction" if active_voice_session else ""
                ),
                "mobility_policy": "in_place" if in_place else "",
                "visual_route": visual_route,
                "visual_resolved": True,
                "target": target if interactive else None,
                "target_identity": (
                    target.get("identity", target.get("target_id", "unknown"))
                    if interactive
                    else None
                ),
                "command_key": voice_slots.get("command_key", ""),
                "command_id": str(data.get("command_id", "")),
                "command_catalog_version": voice_slots.get(
                    "command_catalog_version",
                    "",
                ),
                "intent_source": str(data.get("intent_source", "")),
                "dispatch_role": str(data.get("dispatch_role", "")),
                "specific_event_type": str(
                    data.get("specific_event_type", "")
                ),
                "voice_slots": dict(voice_slots),
            },
        )
        _log.debug(
            "Audio reaction: %s → %s → %s (Lv%d %s)",
            event_type,
            emotion_name,
            behavior_name,
            candidate.priority_level,
            "in_place" if in_place else visual_route,
        )
        return candidate

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
        _log.debug("Need candidate: %s → %s → %s (Lv%d sp=%d %s)",
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
        behavior_context: str = "",
        context_params: dict | None = None,
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

        behavior_name = effective_entry.get("behavior_name")
        if behavior_context:
            contextual_name = effective_entry.get(
                f"{behavior_context}_behavior_name"
            )
            if not isinstance(contextual_name, str) or not contextual_name:
                _log.debug(
                    "Emotion event %s has no %s behavior for route %s",
                    event_type,
                    behavior_context,
                    visual_route,
                )
                return None
            behavior_name = contextual_name
        if not isinstance(behavior_name, str) or not behavior_name:
            return None

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
            behavior_name=behavior_name,
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
            # 情绪类行为使用 10 秒合并门控（区别于姿态/移动/声音类的执行完即触发）。
            cooldown_sec=10.0,
            emotion_priority=EMOTION_PRIORITY.get(em_name, 50),
            interrupt_policy="immediate",
            result_mapping=effective_entry.get("result_mapping"),
            params={
                **route_params,
                **(context_params or {}),
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
        _log.debug("Emotion candidate: %s → %s → %s (Lv%d %s %s)",
                  event_type, effective_entry["intent"],
                  behavior_name, cand.priority_level,
                  interaction_mode, effective_entry.get("variant", ""))
        return cand

    def map_visual_event(
        self,
        event_type: str,
        data: dict,
    ) -> Optional[BehaviorCandidate]:
        """Map whitelisted formal visual events to behavior candidates."""
        entry = self._event_intent.get("visual_direct", {}).get(event_type)
        if entry is None:
            _log.debug("Visual event %s is not a direct behavior event", event_type)
            return None

        visual_events = data.get("events") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1
            or not isinstance(visual_events, list)
            or event_type not in visual_events
        ):
            _log.warning(
                "Rejecting %s: expected matching schema-v1 visual event",
                event_type,
            )
            return None

        intent = str(entry.get("intent", ""))
        behavior_name = self._select_behavior(intent)
        if not intent or behavior_name is None:
            _log.warning(
                "Visual event %s has no configured intent/behavior", event_type
            )
            return None

        active_target = data.get("active_target")
        hands = data.get("hands")
        faces = data.get("faces")
        params = {
            **entry.get("params", {}),
            "visual_header": (
                dict(data["header"])
                if isinstance(data.get("header"), dict)
                else {}
            ),
            "active_target": (
                dict(active_target) if isinstance(active_target, dict) else {}
            ),
            "hands": (
                [dict(item) for item in hands if isinstance(item, dict)]
                if isinstance(hands, list)
                else []
            ),
            "face_count": len(faces) if isinstance(faces, list) else 0,
            "vision_epoch": str(data.get("vision_epoch", "")),
            "snapshot_id": str(data.get("snapshot_id", "")),
            "snapshot_sequence": data.get("sequence"),
            "visual_resolved": True,
        }
        candidate = BehaviorCandidate(
            source="visual_direct",
            source_emotion="",
            trigger_event=event_type,
            intent=intent,
            behavior_name=behavior_name,
            priority_level=self._priority_for(entry["category"]),
            sub_priority=int(entry.get("sub_priority", 12)),
            semantic_rank=int(entry.get("semantic_rank", 3)),
            modality_rank=2,
            intensity=100.0,
            confidence=1.0,
            ttl_sec=float(entry.get("ttl_sec", 8.0)),
            timeout_sec=(
                float(entry["timeout_sec"])
                if entry.get("timeout_sec") is not None
                else None
            ),
            cooldown_sec=(
                float(entry["cooldown_sec"])
                if entry.get("cooldown_sec") is not None
                else None
            ),
            interrupt_policy=str(entry.get("interrupt_policy", "immediate")),
            interactive=False,
            target_required=False,
            target=None,
            interaction_mode="solo",
            result_mapping=None,
            params=params,
        )
        _log.debug(
            "Visual candidate: %s → %s → %s (Lv%d sp=%d)",
            event_type,
            intent,
            behavior_name,
            candidate.priority_level,
            candidate.sub_priority,
        )
        return candidate

    def resolve_alias(self, behavior_name: str) -> str:
        """Resolve a legacy behavior name to its new semantic name."""
        return self._all_aliases.get(behavior_name, behavior_name)

    def _validated_audio_reaction(
        self,
        event_type: str,
        data: dict,
    ) -> tuple[dict, dict[str, str]] | None:
        entry = self._event_intent.get("audio_reaction", {}).get(event_type)
        if not isinstance(entry, dict):
            _log.debug("Audio event %s is not an audio reaction", event_type)
            return None
        voice_slots = self._validate_audio_contract(
            event_type,
            data,
            intent_entry=entry,
            expected_dispatch_role="social_reaction",
        )
        if voice_slots is None:
            return None
        expected_social = str(entry.get("expected_social", "")).strip()
        if (
            not expected_social
            or str(data.get("social", "")).strip() != expected_social
            or str(data.get("emotion", "")).strip() != expected_social
            or str(data.get("intent", "")).strip() != "NONE"
            or str(data.get("action", "")).strip() != "NONE"
            or str(data.get("control", "")).strip() != "NONE"
            or data.get("is_executable") is not False
        ):
            _log.warning(
                "Rejecting %s: invalid social-reaction authority fields",
                event_type,
            )
            return None
        return entry, voice_slots

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _validate_audio_contract(
        event_type: str,
        data: dict,
        *,
        intent_entry: dict,
        expected_dispatch_role: str = "specific_command",
    ) -> dict[str, str] | None:
        return validate_audio_contract(
            event_type, data, logger=_log, intent_entry=intent_entry,
            expected_dispatch_role=expected_dispatch_role,
        )

    def _build_audio_candidate(self, event_type: str, data: dict,
                               intent_entry: dict,
                               voice_slots: dict[str, str]) -> Optional[BehaviorCandidate]:
        intent = intent_entry.get("intent", "")
        if not intent:
            return None

        behavior_name = self._select_behavior(intent)
        if behavior_name is None:
            return None

        try:
            confidence = float(
                data.get("intent_confidence", data.get("wake_confidence", 0.8))
            )
        except (TypeError, ValueError):
            return None
        if not math.isfinite(confidence):
            return None
        confidence = max(0.0, min(1.0, confidence))

        # Voice never owns visual target selection.  Preserve an explicitly
        # resolved target reference for compatibility, but never manufacture a
        # stable id from speaker identity.
        target_track_id = data.get("target_track_id")
        target_identity = data.get("target_identity")
        explicit_target_id = str(data.get("target_id", "")).strip()
        target = None
        if explicit_target_id and target_track_id is not None:
            target = {
                "target_type": "human",
                "target_id": explicit_target_id,
                "track_id": target_track_id,
                "identity": target_identity or "unknown",
            }

        need_gate = self._normalize_audio_need_gate(
            event_type,
            intent_entry.get("need_gate"),
        )
        if need_gate is None:
            return None

        interaction_id = str(data.get("interaction_id", "")).strip()
        utterance_id = str(data.get("utterance_id", "")).strip()
        session_role = (
            "wake_orientation"
            if event_type == "EVT_VOICE_WAKEUP"
            else "voice_command"
        )
        session_preempt_rank = 10 if session_role == "wake_orientation" else 0
        header = data.get("header") if isinstance(data.get("header"), dict) else {}

        params = {
            "lifecycle_scope": "voice_session",
            "completion_policy": "bounded",
            "cancel_on_voice_idle": True,
            **intent_entry.get("params", {}),
            "asr_text": data.get("asr_text", ""),
            "intent_confidence": confidence,
            "interaction_id": interaction_id,
            "wake_id": str(data.get("wake_id", "")) if session_role == "wake_orientation" else "",
            "utterance_id": utterance_id,
            "audio_event_key": "%s:%s:%s" % (
                interaction_id, utterance_id, event_type
            ),
            "wake_event_stamp": header.get("stamp"),
            "session_role": session_role,
            "session_preempt_rank": session_preempt_rank,
            "target_track_id": target_track_id,
            "target_identity": target_identity,
            "command_key": voice_slots.get("command_key", ""),
            "command_id": str(data.get("command_id", "")),
            "command_catalog_version": voice_slots.get(
                "command_catalog_version",
                "",
            ),
            "intent_source": str(data.get("intent_source", "")),
            "dispatch_role": str(data.get("dispatch_role", "")),
            "specific_event_type": str(data.get("specific_event_type", "")),
            "nlu_protocol": str(data.get("nlu_protocol", "")),
            "raw_nlu_tag": str(data.get("raw_nlu_tag", "")),
            "voice_slots": dict(voice_slots),
        }
        if need_gate:
            params["need_gate"] = need_gate
        object_name = voice_slots.get("object_name", "")
        if object_name and object_name != "NONE":
            params["object_name"] = object_name
            params["object_mention"] = voice_slots.get("object_mention", "")
            params["object_match_source"] = voice_slots.get(
                "object_match_source", ""
            )
            params["object_catalog_version"] = voice_slots.get(
                "object_catalog_version", ""
            )
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
            semantic_rank=int(intent_entry.get(
                "semantic_rank",
                2 if event_type == "EVT_VOICE_WAKEUP" else 1,
            )),
            modality_rank=1,
            intensity=min(confidence * 100, 100.0),
            confidence=confidence,
            ttl_sec=float(intent_entry.get("ttl_sec", 8.0)),
            timeout_sec=(
                float(intent_entry["timeout_sec"])
                if intent_entry.get("timeout_sec") is not None else None
            ),
            cooldown_sec=(
                float(intent_entry["cooldown_sec"])
                if intent_entry.get("cooldown_sec") is not None else None
            ),
            interrupt_policy=str(
                intent_entry.get("interrupt_policy", "immediate")
            ),
            interactive=target is not None,
            target=target,
            interaction_mode="interactive" if target else "solo",
            result_mapping=None,
            params=params,
        )
        _log.debug("Audio candidate: %s → %s → %s (Lv%d sp=%d)",
                  event_type, intent, behavior_name,
                  cand.priority_level, cand.sub_priority)
        return cand

    @staticmethod
    def _normalize_audio_need_gate(
        event_type: str,
        raw_gate: Any,
    ) -> dict[str, Any] | None:
        """Validate a configured authoritative internal-need gate.

        An empty mapping means the route is not need-gated.  ``None`` signals
        malformed configuration so the command fails closed.
        """
        if raw_gate is None:
            return {}
        if not isinstance(raw_gate, dict):
            _log.error("Audio route %s has malformed need_gate", event_type)
            return None
        demand = str(raw_gate.get("demand", "")).strip()
        operator = str(raw_gate.get("operator", "")).strip()
        try:
            threshold = float(raw_gate["threshold"])
        except (KeyError, TypeError, ValueError):
            threshold = float("nan")
        if (
            not demand
            or operator != "gt"
            or not math.isfinite(threshold)
            or not 0.0 <= threshold <= 100.0
        ):
            _log.error(
                "Audio route %s has invalid need_gate demand=%r "
                "operator=%r threshold=%r",
                event_type,
                demand,
                operator,
                raw_gate.get("threshold"),
            )
            return None
        return {
            "demand": demand,
            "operator": operator,
            "threshold": threshold,
        }

    def build_voice_approach_candidate(
        self,
        *,
        interaction_id: str,
        target: dict[str, Any],
        wake_id: str,
        speaker_id: str,
        speaker_role: str,
        speaker_status: str,
        stand_off_distance_m: float,
        timeout_sec: float,
        ttl_sec: float,
    ) -> BehaviorCandidate:
        """Build the internal continuation after wake-speaker resolution."""
        behavior_name = self._select_behavior("approach_wake_speaker")
        if behavior_name != "approach_voice_caller":
            raise ValueError(
                "approach_wake_speaker must map exactly to "
                "approach_voice_caller"
            )
        target_ref = dict(target)
        params = {
            "interaction_id": interaction_id,
            "session_role": "wake_approach",
            "session_preempt_rank": 20,
            "strict_target_lock": True,
            "allow_target_switch": False,
            "wake_id": wake_id,
            "speaker_id": speaker_id,
            "speaker_role": speaker_role,
            "speaker_status": speaker_status,
            "stand_off_distance_m": float(stand_off_distance_m),
            "approach_timeout_sec": float(timeout_sec),
            "target": target_ref,
        }
        return BehaviorCandidate(
            source="audio_session",
            trigger_event="INTERNAL_WAKE_SPEAKER_RESOLVED",
            intent="approach_wake_speaker",
            behavior_name=behavior_name,
            priority_level=self._priority_for("external_interaction"),
            sub_priority=2,
            intensity=100.0,
            confidence=float(
                target_ref.get(
                    "detection_confidence",
                    target_ref.get("confidence", 0.8),
                )
            ),
            ttl_sec=float(ttl_sec),
            timeout_sec=float(timeout_sec),
            cooldown_sec=0.0,
            interrupt_policy="immediate",
            interactive=True,
            target_required=True,
            target=target_ref,
            interaction_mode="interactive",
            variant="wake_speaker",
            params=params,
        )

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
