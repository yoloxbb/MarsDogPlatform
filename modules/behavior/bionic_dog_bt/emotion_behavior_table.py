"""Emotion-driven behavior selection table.

Maps (dominant_emotion, intensity_zone, interaction_type) → candidate behaviors.
At injection time, the system:
  1. Finds the dominant emotion (highest current value)
  2. Determines the intensity zone
  3. Checks check_person() for interactive vs solo
  4. Randomly picks a behavior from the matching pool

Each behavior name maps to an action sequence in action_catalog.py.
"""

from __future__ import annotations

import random
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# Emotion Zone Definitions
# ═══════════════════════════════════════════════════════════════════════════════

EMOTION_ZONES: dict[str, list[tuple[float, float, str]]] = {
    "Calm":    [(0, 100, "normal")],
    "Joy":     [(40, 60, "low"), (61, 85, "mid"), (86, 100, "high")],
    "Excite":  [(40, 70, "low"), (71, 100, "high")],
    "Anxiety": [(25, 50, "low"), (51, 100, "high")],
    "Fear":    [(30, 60, "low"), (61, 100, "high")],
    "Curious": [(20, 50, "low"), (51, 100, "high")],
}


def get_emotion_zone(emotion_name: str, value: float) -> Optional[str]:
    """Get the intensity zone label for an emotion value."""
    zones = EMOTION_ZONES.get(emotion_name, [])
    for lo, hi, label in zones:
        if lo <= value <= hi:
            return label
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Emotion → Behavior Table
# ═══════════════════════════════════════════════════════════════════════════════
# Keys: (emotion_name, zone_label, interaction)
#   interaction: "solo" or "interactive"
# Values: list of behavior_name strings

EMOTION_BEHAVIOR_TABLE: dict[tuple[str, str, str], list[str]] = {

    # ── Calm 0-100 ──────────────────────────────────────────────────────────
    ("Calm", "normal", "solo"): [
        "restInPlace", "sleepOnSide", "stretchLazily",
        "lickPaws", "yawnSlowly", "exposeBelly", "waitAtDoor",
    ],
    ("Calm", "normal", "interactive"): [
        "cuddlePose", "pawAtOwner",
    ],

    # ── Joy 40-60 ───────────────────────────────────────────────────────────
    ("Joy", "low", "solo"): [
        "wagTailGently",
    ],
    ("Joy", "low", "interactive"): [
        "wagTailGently",
    ],

    # ── Joy 61-85 ───────────────────────────────────────────────────────────
    ("Joy", "mid", "solo"): [
        "wagTailFast", "hopInPlace",
    ],
    ("Joy", "mid", "interactive"): [
        "nudgeWithNose", "playBow",
    ],

    # ── Joy 86-100 ──────────────────────────────────────────────────────────
    ("Joy", "high", "solo"): [
        "tailUpAndWag", "spinInCircle", "runBackAndForth", "rollOverShowBelly",
    ],
    ("Joy", "high", "interactive"): [
        "pounceForward", "barkShortExcited",
    ],

    # ── Excite 40-70 ────────────────────────────────────────────────────────
    ("Excite", "low", "solo"): [
        "carryAndShake", "wiggleBody", "trotAndBounce",
    ],
    ("Excite", "low", "interactive"): [
        "begForFood",
    ],

    # ── Excite 71-100 ───────────────────────────────────────────────────────
    ("Excite", "high", "solo"): [
        "moveRapidly", "circleAround", "zoomiesRun",
    ],
    ("Excite", "high", "interactive"): [
        "jumpOnPerson", "barkOrWhine", "mouthingGently", "pawOnKnee", "fetchToy",
    ],

    # ── Anxiety 25-50 ───────────────────────────────────────────────────────
    ("Anxiety", "low", "solo"): [
        "paceBackAndForth", "whineLow", "stareIntently",
    ],
    ("Anxiety", "low", "interactive"): [
        "headTilt",
    ],

    # ── Anxiety 51-100 ──────────────────────────────────────────────────────
    ("Anxiety", "high", "solo"): [
        "scratchFrequently", "whineHigh", "bodyStiffen",
        "tuckTail", "dilatePupils", "hideAway",
    ],
    ("Anxiety", "high", "interactive"): [
        "hideAway",
    ],

    # ── Fear 30-60 ──────────────────────────────────────────────────────────
    ("Fear", "low", "solo"): [
        "freezeAlert", "walkAway", "retreatWithTailTucked", "growlLow",
    ],
    ("Fear", "low", "interactive"): [
        "freezeAlert",
    ],

    # ── Fear 61-100 ─────────────────────────────────────────────────────────
    ("Fear", "high", "solo"): [
        "fleeQuickly", "avoidAndHide", "trembleShake", "loseControl", "dilatePupils",
    ],
    ("Fear", "high", "interactive"): [
        "fleeQuickly",
    ],

    # ── Curious 20-50 ───────────────────────────────────────────────────────
    ("Curious", "low", "solo"): [
        "tailWagLevel", "stareIntently",
    ],
    ("Curious", "low", "interactive"): [
        "headTilt",
    ],

    # ── Curious 51-100 ──────────────────────────────────────────────────────
    ("Curious", "high", "solo"): [
        "approachSlowly", "sniffGround", "pawAtObject",
        "followMovement", "circleInspect",
    ],
    ("Curious", "high", "interactive"): [
        "approachSlowly", "followMovement",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Selection Functions
# ═══════════════════════════════════════════════════════════════════════════════

def select_emotion_behavior(emotion_name: str, value: float,
                            interactive: bool = False) -> Optional[str]:
    """Select a random behavior for the given emotion/value/interaction.

    Returns a behavior_name string, or None if no match.
    """
    zone = get_emotion_zone(emotion_name, value)
    if zone is None:
        return None

    interaction = "interactive" if interactive else "solo"
    candidates = EMOTION_BEHAVIOR_TABLE.get((emotion_name, zone, interaction))

    if not candidates:
        # Fall back to solo if interactive has no candidates
        candidates = EMOTION_BEHAVIOR_TABLE.get((emotion_name, zone, "solo"))

    if not candidates:
        return None

    return random.choice(candidates)


def get_dominant_emotion(emotions: dict[str, float]) -> Optional[tuple[str, float]]:
    """Find the dominant (highest value) emotion and its value.

    When multiple emotions have the same value, tiebreaker priority:
    Fear > Anxiety > Excite > Joy > Curious > Calm
    """
    if not emotions:
        return None
    max_val = max(emotions.values())
    candidates = [n for n, v in emotions.items() if v == max_val]
    priority = {"Fear": 0, "Anxiety": 1, "Excite": 2, "Joy": 3, "Curious": 4, "Calm": 5}
    candidates.sort(key=lambda n: priority.get(n, 99))
    dominant = candidates[0]
    return dominant, emotions[dominant]


# ═══════════════════════════════════════════════════════════════════════════════
# All emotion-driven behavior names (for mapping and relevance checks)
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_emotion_behaviors() -> set[str]:
    """Return the set of all behavior names in the table."""
    result: set[str] = set()
    for candidates in EMOTION_BEHAVIOR_TABLE.values():
        result.update(candidates)
    return result


def get_source_emotion(behavior_name: str) -> Optional[str]:
    """Given a behavior name, find which emotion it belongs to."""
    for (emotion, zone, interaction), candidates in EMOTION_BEHAVIOR_TABLE.items():
        if behavior_name in candidates:
            return emotion
    return None
