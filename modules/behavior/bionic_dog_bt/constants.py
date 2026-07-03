"""Constants for priority levels, status values, and interrupt policies."""

# ── Priority Levels ──────────────────────────────────────────────────────────
# Lower number = higher priority
PRIORITY_LEVELS = {
    "SYSTEM": 0,
    "PHYSIO_URGENT": 1,
    "EXTERNAL_INTERACTION": 2,
    "PHYSIO_NORMAL": 3,
    "PSYCHOLOGICAL": 4,
    "EMOTION_EXPRESSION": 5,
    "IDLE": 6,
}

LEVEL_NAMES = {
    0: "Lv0_System",
    1: "Lv1_PhysioUrgent",
    2: "Lv2_ExternalInteraction",
    3: "Lv3_PhysioNormal",
    4: "Lv4_Psychological",
    5: "Lv5_EmotionExpression",
    6: "Lv6_Idle",
}

# ── Behavior Tree Status ─────────────────────────────────────────────────────
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_RUNNING = "RUNNING"
STATUS_CANCELED = "CANCELED"

# ── Interrupt Policies ───────────────────────────────────────────────────────
INTERRUPT_IMMEDIATE = "immediate"
INTERRUPT_SAFE_POINT = "safe_point"
INTERRUPT_NON_INTERRUPTIBLE = "non_interruptible"

# ── Preemption ───────────────────────────────────────────────────────────────
# Min value delta required for same-level preemption
SAME_LEVEL_PREEMPTION_DELTA = 15

# ── Emotion → Behavior Mapping ───────────────────────────────────────────────
# Maps behavior_name → emotion_name for relevance checking.
# Emotion names align with ROS2 /emotion/state fields.
EMOTION_BEHAVIOR_MAP = {
    "express_happy": "Joy",
    "express_fear": "Fear",
    "express_curiosity": "Curious",
}

# ── Need → Behavior Mapping ──────────────────────────────────────────────────
# Maps behavior_name → need_name for relevance checking.
# Need names align with ROS2 /internal_need/state demands fields.
NEED_BEHAVIOR_MAP = {
    "seek_food_or_water": "Hunger",
    "excretion_request": "Bladder",
    "sleep_request": "Sleepiness",
    "clean_self": "Cleanliness",
    "seek_social_interaction": "Social",
    "explore_environment": "Exploration",
}

# ── Emotion Defaults (ROS2-aligned) ──────────────────────────────────────────
# Decay rates match emotion_engine_node natural decay (per second).
# overflow_threshold is the value above which an emotion "overflows"
# and generates a behavior candidate.
DEFAULT_EMOTION_CONFIG = {
    "Joy":      {"overflow_threshold": 70.0, "decay_rate": 2.0},
    "Excite":   {"overflow_threshold": 70.0, "decay_rate": 3.0},
    "Anxiety":  {"overflow_threshold": 50.0, "decay_rate": 1.5},
    "Fear":     {"overflow_threshold": 60.0, "decay_rate": 4.0},
    "Curious":  {"overflow_threshold": 50.0, "decay_rate": 2.0},
    "Calm":     {"overflow_threshold": 60.0, "decay_rate": 0.0},
}

# ── Need Defaults (ROS2-aligned) ─────────────────────────────────────────────
# trigger_threshold: value above/below which the need is TRIGGERED
# overflow_threshold: value above/below which the need is OVERFLOW
# operator: "gt" = greater-than, "lt" = less-than (e.g. Energy)
DEFAULT_NEED_CONFIG = {
    "Hunger":      {"trigger_threshold": 70, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Bladder":     {"trigger_threshold": 75, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Sleepiness":  {"trigger_threshold": 65, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Cleanliness": {"trigger_threshold": 70, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Energy":      {"trigger_threshold": 20, "trigger_op": "lt",
                    "overflow_threshold": 10, "overflow_op": "lt"},
    "Social":      {"trigger_threshold": 60, "trigger_op": "gt",
                    "overflow_threshold": 80, "overflow_op": "gt"},
    "Exploration": {"trigger_threshold": 60, "trigger_op": "gt",
                    "overflow_threshold": 80, "overflow_op": "gt"},
}

# ── Need Level Constants ─────────────────────────────────────────────────────
NEED_LEVEL_NORMAL = "NORMAL"
NEED_LEVEL_TRIGGERED = "TRIGGERED"
NEED_LEVEL_OVERFLOW = "OVERFLOW"

# ── Voice Command → Behavior Mapping ─────────────────────────────────────────
# Maps ROS2 /perception/audio_event command_id → behavior_name.
# Used when event_type == "EVT_VOICE_COMMAND_KNOWN".
COMMAND_BEHAVIOR_MAP = {
    "CMD_SIT": "respond_owner_call",       # 坐下 → 响应主人（靠近+坐下）
    "CMD_COME_HERE": "respond_owner_call", # 过来 → 响应主人
    "CMD_HAND": "respond_touch_head",      # 握手 → 互动（摸头响应）
    "CMD_FIVE": "respond_touch_head",      # 击掌 → 互动
    "CMD_FOLLOW": "respond_owner_call",    # 随行 → 响应主人
    "CMD_STOP": "emergency_stop",          # 停止 → 紧急停止
    "CMD_PRAISE": "express_happy",         # 表扬 → 开心表达
    "CMD_COMFORT": "express_happy",        # 安慰 → 开心表达（互动模式）
    "CMD_ENCOUR": "express_happy",         # 鼓励 → 开心表达
}

# ── Default Behaviors ────────────────────────────────────────────────────────
DEFAULT_IDLE_BEHAVIOR = "idle_look_around"
