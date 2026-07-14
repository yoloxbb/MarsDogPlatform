"""Intent Mapper — event → category → intent → behavior_name pipeline.

Loads event_intent_map.yaml, intent_action_pool.yaml, emotion_behavior_map.yaml,
behavior_categories.yaml, and legacy_behavior_aliases.yaml.

BehaviorCandidate: structured dataclass with sub_priority, intensity, level,
variant, interaction_mode, and target fields.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from bionic_dog_bt.logger import get_logger

_log = get_logger("intent_mapper")

# ── Whitelists ────────────────────────────────────────────────────────────

ALLOWED_AUDIO_DIRECT_EVENTS = {
    "EVT_VOICE_CALL_NAME",
    "EVT_VOICE_COMMAND_KNOWN",
    "EVT_VOICE_COMMAND_UNKNOWN",
}

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
    trigger_event: str = ""       # e.g. "CMD_SIT", "EMO_JOY_HIGH"
    intent: str = ""              # e.g. "command_sit", "express_joy"

    priority_level: int = 6
    sub_priority: int = 0

    intensity: float | None = None
    level: str | None = None      # LOW / MID / HIGH
    variant: str | None = None    # e.g. "joy_mid", "shallow", "boundary"

    interactive: bool = False
    target_required: bool = False
    target: dict[str, Any] | None = None
    interaction_mode: str = "solo"  # solo / interactive

    params: dict[str, Any] = field(default_factory=dict)
    result_mapping: dict[str, Any] | None = None

    interrupt_policy: str = "safe_point"
    ttl_sec: float = 10.0
    confidence: float = 0.8
    source_emotion: str = ""
    source_demand: str = ""
    command_id: str = ""
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
        """Convert to dict for CandidatePool compatibility."""
        return {
            "behavior_name": self.behavior_name,
            "priority_level": self.priority_level,
            "sub_priority": self.sub_priority,
            "value": self.intensity or 50.0,
            "confidence": self.confidence,
            "need_type": _category_to_need_type(self._category_from_level()),
            "source_emotion": self.source_emotion,
            "dedup_key": self.dedup_key,
            "params": {
                "schema_version": "1.0",
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
                "command_id": self.command_id,
                "candidate_id": self.candidate_id,
                "sub_priority": self.sub_priority,
                "result_mapping": self.result_mapping,
                **self.params,
            },
            "timeout_sec": _default_timeout_for_level(self.priority_level),
            "cooldown_sec": _default_cooldown_for_level(self.priority_level),
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
    defaults = {0: 5.0, 1: 8.0, 2: 60.0, 3: 30.0, 4: 25.0, 5: 8.0, 6: 30.0}
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
        if config_dir is None:
            src_root = Path(__file__).resolve().parent.parent
            config_dir = str(src_root / "config")

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
        """Map an audio_event to a BehaviorCandidate (whitelist only)."""
        if event_type not in ALLOWED_AUDIO_DIRECT_EVENTS:
            if event_type in AUDIO_EVENTS_FOR_EMOTION_ENGINE:
                _log.debug("Audio event %s ignored (→ emotion_engine)", event_type)
            return None

        audio_map = self._event_intent.get("audio_direct", {})

        if event_type == "EVT_VOICE_CALL_NAME":
            return self._build_audio_candidate(
                event_type, data,
                intent_entry=audio_map.get("EVT_VOICE_CALL_NAME", {}))

        if event_type == "EVT_VOICE_COMMAND_KNOWN":
            command_id = data.get("command_id", "")
            if not data.get("is_executable", True):
                return None
            cmd_entry = audio_map.get("EVT_VOICE_COMMAND_KNOWN", {})
            cmd_info = cmd_entry.get("command_map", {}).get(command_id)
            if cmd_info is None:
                return None
            return self._build_audio_candidate(event_type, data, intent_entry=cmd_info)

        if event_type == "EVT_VOICE_COMMAND_UNKNOWN":
            entry = audio_map.get("EVT_VOICE_COMMAND_UNKNOWN", {})
            if not entry.get("enabled", False):
                return None
            return self._build_audio_candidate(event_type, data, intent_entry=entry)

        return None

    def map_need_event(self, event_type: str, data: dict) -> Optional[BehaviorCandidate]:
        """Map a need signal_event to a BehaviorCandidate via event_intent_map."""
        need_map = self._event_intent.get("need", {})
        entry = need_map.get(event_type)
        if entry is None:
            _log.debug("Need event %s not in event_intent_map", event_type)
            return None

        intent = entry["intent"]
        behavior_name = entry.get("behavior_name") or self._select_behavior(intent)
        if behavior_name is None:
            return None

        demand = data.get("demand", "")
        value = float(data.get("value", 80))
        variant = entry.get("variant")
        level = data.get("level", "")

        cand = BehaviorCandidate(
            source="need",
            source_demand=demand,
            trigger_event=event_type,
            intent=intent,
            behavior_name=behavior_name,
            priority_level=self._priority_for(entry["category"]),
            sub_priority=entry.get("sub_priority", 0),
            intensity=value,
            level=level or _level_from_event(event_type),
            variant=variant,
            interactive=False,
            target_required=False,
            interaction_mode="solo",
            ttl_sec=30.0,
            confidence=0.8,
            result_mapping=entry.get("result_mapping", self._default_result_mapping(behavior_name)),
            params={
                "intensity": value,
                "level": level or _level_from_event(event_type),
                "variant": variant,
            },
        )
        _log.info("Need candidate: %s → %s → %s (Lv%d sp=%d %s)",
                  event_type, intent, behavior_name,
                  cand.priority_level, cand.sub_priority, variant or "")
        return cand

    def map_emotion_event(self, event_type: str, data: dict,
                          interactive: bool = False,
                          target: dict = None) -> Optional[BehaviorCandidate]:
        """Map an emotion signal_event to a BehaviorCandidate via emotion_behavior_map."""
        em_map = self._emotion_map.get("emotion_behavior_map", {})
        entry = em_map.get(event_type)
        if entry is None:
            _log.debug("Emotion event %s not in emotion_behavior_map", event_type)
            return None

        em_name = _event_to_emotion_name(event_type)
        value = float(data.get("value", 80))

        interaction_mode = "interactive" if (interactive and target) else "solo"

        cand = BehaviorCandidate(
            source="emotion",
            source_emotion=em_name,
            trigger_event=event_type,
            intent=entry["intent"],
            behavior_name=entry["behavior_name"],
            priority_level=entry["priority_level"],
            sub_priority=entry.get("sub_priority", 0),
            intensity=value,
            level=entry.get("level"),
            variant=entry.get("variant"),
            interactive=interactive,
            target_required=False,
            target=target if interaction_mode == "interactive" else None,
            interaction_mode=interaction_mode,
            ttl_sec=10.0,
            confidence=0.85,
            result_mapping=entry.get("result_mapping"),  # null for emotions
            params={
                "emotion": em_name,
                "intensity": value,
                "level": entry.get("level"),
                "variant": entry.get("variant"),
                "interaction_mode": interaction_mode,
                "interactive": interactive,
                "target": target if interaction_mode == "interactive" else None,
            },
        )
        _log.info("Emotion candidate: %s → %s → %s (Lv%d %s %s)",
                  event_type, entry["intent"], entry["behavior_name"],
                  cand.priority_level, interaction_mode, entry.get("level", ""))
        return cand

    def map_visual_event(self, event_type: str, data: dict) -> None:
        """Visual events MUST NOT generate behavior candidates."""
        return None

    def resolve_alias(self, behavior_name: str) -> str:
        """Resolve a legacy behavior name to its new semantic name."""
        return self._all_aliases.get(behavior_name, behavior_name)

    # ── Social fine-graining ─────────────────────────────────────────────

    def refine_social_intent(self, social_value: float,
                             has_animal_target: bool = False,
                             has_human_target: bool = False) -> dict:
        """Refine coarse NEED_SOCIAL_TRIGGERED into fine-grained intent.

        Returns dict with keys: intent, behavior_name, variant, target_required, interactive.
        """
        if social_value <= 70:
            if has_animal_target:
                return {"intent": "animal_boundary_test",
                        "behavior_name": "testAnimalBoundary",
                        "variant": "boundary",
                        "target_required": True, "interactive": True}
            elif has_human_target:
                return {"intent": "human_resource_interaction",
                        "behavior_name": "requestResourceFromHuman",
                        "variant": "resource",
                        "target_required": True, "interactive": True}
            else:
                return {"intent": "social_seek",
                        "behavior_name": "seekHumanInteraction",
                        "variant": "general",
                        "target_required": False, "interactive": False}
        elif social_value <= 85:
            if has_animal_target:
                return {"intent": "animal_social_greet",
                        "behavior_name": "greetAnimal",
                        "variant": "greeting",
                        "target_required": True, "interactive": True}
            elif has_human_target:
                return {"intent": "human_attention_interaction",
                        "behavior_name": "seekHumanInteraction",
                        "variant": "attention",
                        "target_required": True, "interactive": True}
            else:
                return {"intent": "social_seek",
                        "behavior_name": "seekHumanInteraction",
                        "variant": "seeking",
                        "target_required": False, "interactive": False}
        else:  # 86-100
            if has_animal_target:
                return {"intent": "animal_play_invite",
                        "behavior_name": "inviteAnimalToPlay",
                        "variant": "play",
                        "target_required": True, "interactive": True}
            elif has_human_target:
                return {"intent": "human_play_invite",
                        "behavior_name": "inviteHumanToPlay",
                        "variant": "play",
                        "target_required": True, "interactive": True}
            else:
                return {"intent": "social_seek",
                        "behavior_name": "seekHumanInteraction",
                        "variant": "seeking",
                        "target_required": False, "interactive": False}

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_audio_candidate(self, event_type: str, data: dict,
                               intent_entry: dict) -> Optional[BehaviorCandidate]:
        intent = intent_entry.get("intent", "")
        if not intent:
            return None

        behavior_name = self._select_behavior(intent)
        if behavior_name is None:
            return None

        command_id = data.get("command_id", "")
        confidence = float(data.get("intent_confidence", 0.8))

        cand = BehaviorCandidate(
            source="audio_direct",
            command_id=command_id,
            trigger_event=command_id or event_type,
            intent=intent,
            behavior_name=behavior_name,
            priority_level=self._priority_for(intent_entry["category"]),
            sub_priority=intent_entry.get("sub_priority", 0),
            intensity=min(confidence * 100, 100.0),
            confidence=confidence,
            ttl_sec=8.0,
            result_mapping=None,
            params={
                "command_id": command_id,
                "asr_text": data.get("asr_text", ""),
                "intent_confidence": confidence,
            },
        )
        _log.info("Audio candidate: %s → %s → %s (Lv%d sp=%d)",
                  command_id or event_type, intent, behavior_name,
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
            "defecate": {"action_type": "ACTION_DEFECATE", "demand_type": "Bladder"},
            "cleanSelf": {"action_type": "ACTION_GROOM", "demand_type": "Cleanliness"},
            "sleepNow": {"action_type": "ACTION_SLEEP", "demand_type": "Sleepiness"},
            "recharge": {"action_type": "ACTION_RECHARGE", "demand_type": "Energy"},
            "restInPlace": None,  # low energy rest, no result event
        }
        return mapping.get(behavior_name)


def _level_from_event(event_type: str) -> str:
    if "OVERFLOW" in event_type:
        return "OVERFLOW"
    if "TRIGGERED" in event_type:
        return "TRIGGERED"
    return ""


def _event_to_emotion_name(event_type: str) -> str:
    mapping = {
        "EMO_JOY": "Joy", "EMO_EXCITE": "Excite",
        "EMO_ANXIETY": "Anxiety", "EMO_FEAR": "Fear",
        "EMO_CURIOUS": "Curious", "EMO_CALM": "Calm",
    }
    for prefix, name in mapping.items():
        if event_type.startswith(prefix):
            return name
    return ""


def get_emotion_name_from_event(event_type: str) -> str:
    return _event_to_emotion_name(event_type)
