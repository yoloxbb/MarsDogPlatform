"""Authoritative state/signal consumption through the existing BT state ports.

Validation, atomic update, recovery and candidate ordering remain domain-owned.
The ROS node supplies blackboard, candidate and asynchronous-resolution ports.
"""
from __future__ import annotations
import json
from bionic_dog_bt.constants import EMOTION_V2_EVENT_TO_NAME, NEED_LEVEL_NORMAL, NEED_LEVEL_OVERFLOW, NEED_LEVEL_URGENT, NEED_V2_ACTIVE_LEVELS, NEED_V2_EVENT_TO_STATE

def _is_json_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _need_level_event(demand: str, level: str) -> str:
    suffix = "RECOVERED" if level == NEED_LEVEL_NORMAL else level
    return f"NEED_{demand.upper()}_{suffix}"


def _need_level_from_value(
    value: float,
    *,
    trigger_threshold: float,
    urgent_threshold: float | None,
    overflow_threshold: float | None,
) -> str:
    """Derive a V2 need level; every V2 comparison is strict ``gt``."""
    if overflow_threshold is not None and value > overflow_threshold:
        return NEED_LEVEL_OVERFLOW
    if urgent_threshold is not None and value > urgent_threshold:
        return NEED_LEVEL_URGENT
    if value > trigger_threshold:
        return "TRIGGERED"
    return NEED_LEVEL_NORMAL


def _parse_need_thresholds(
    payload: dict,
    context: str,
    *,
    require_overflow_operator: bool,
) -> tuple[float, str, float | None, str | None, float | None, str | None]:
    """Validate and return the V2 threshold metadata."""
    required_fields = {
        "triggerThreshold",
        "triggerOperator",
        "urgentThreshold",
        "urgentOperator",
        "overflowThreshold",
    }
    if require_overflow_operator:
        required_fields.add("overflowOperator")
    missing = sorted(required_fields - payload.keys())
    if missing:
        raise ValueError(
            f"{context} missing V2 threshold fields: {', '.join(missing)}"
        )

    trigger_threshold = payload.get("triggerThreshold")
    trigger_operator = payload.get("triggerOperator")
    if not _is_json_number(trigger_threshold):
        raise ValueError(f"{context}.triggerThreshold must be numeric")
    if trigger_operator != "gt":
        raise ValueError(f"{context}.triggerOperator must be 'gt'")

    urgent_threshold = payload.get("urgentThreshold")
    urgent_operator = payload.get("urgentOperator")
    if urgent_threshold is None and urgent_operator is None:
        pass
    elif (
        not _is_json_number(urgent_threshold)
        or urgent_operator != "gt"
    ):
        raise ValueError(
            f"{context}.urgentThreshold/urgentOperator must be null/null "
            "or numeric/'gt'"
        )

    overflow_threshold = payload.get("overflowThreshold")
    overflow_operator = payload.get("overflowOperator")
    if overflow_threshold is None:
        if overflow_operator is not None:
            raise ValueError(
                f"{context}.overflowOperator requires overflowThreshold"
            )
    else:
        if not _is_json_number(overflow_threshold):
            raise ValueError(f"{context}.overflowThreshold must be numeric or null")
        if overflow_operator is None and not require_overflow_operator:
            overflow_operator = "gt"
        if overflow_operator != "gt":
            raise ValueError(f"{context}.overflowOperator must be 'gt'")

    normalized_trigger = float(trigger_threshold)
    normalized_urgent = (
        float(urgent_threshold) if urgent_threshold is not None else None
    )
    normalized_overflow = (
        float(overflow_threshold) if overflow_threshold is not None else None
    )
    if (
        normalized_urgent is not None
        and normalized_urgent <= normalized_trigger
    ):
        raise ValueError(f"{context}.urgentThreshold must exceed triggerThreshold")
    previous_threshold = (
        normalized_urgent
        if normalized_urgent is not None
        else normalized_trigger
    )
    if (
        normalized_overflow is not None
        and normalized_overflow <= previous_threshold
    ):
        raise ValueError(
            f"{context}.overflowThreshold must exceed earlier thresholds"
        )

    return (
        normalized_trigger,
        trigger_operator,
        normalized_urgent,
        urgent_operator,
        normalized_overflow,
        overflow_operator,
    )

def on_emotion_state_ros2(self, msg):
    """Handle /emotion/state (periodic, 1Hz).

    V2 state is authoritative for both current values and recovery. It
    never generates candidates; only /emotion/signal_event does that.
    """
    try:
        data = json.loads(msg.data)
        if data.get("schema_version") != "2.0":
            raise ValueError(
                "unsupported emotion schema_version "
                f"{data.get('schema_version')!r}; expected '2.0'"
            )

        emotions = data.get("emotions")
        if not isinstance(emotions, dict):
            raise ValueError("emotions must be an object")

        # Validate the entire snapshot before mutating the blackboard.
        updates = []
        for name, emotion_info in emotions.items():
            if name not in EMOTION_V2_EVENT_TO_NAME.values():
                raise ValueError(f"unknown emotion {name!r}")
            if not isinstance(emotion_info, dict):
                raise ValueError(f"emotions.{name} must be an object")

            value = emotion_info.get("value")
            triggered = emotion_info.get("triggered")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"emotions.{name}.value must be numeric")
            if not isinstance(triggered, bool):
                raise ValueError(f"emotions.{name}.triggered must be boolean")

            trigger_threshold = emotion_info.get("triggerThreshold")
            if (
                trigger_threshold is not None
                and (
                    isinstance(trigger_threshold, bool)
                    or not isinstance(trigger_threshold, (int, float))
                )
            ):
                raise ValueError(
                    f"emotions.{name}.triggerThreshold must be numeric"
                )
            trigger_operator = emotion_info.get("triggerOperator")
            if trigger_operator is not None and not isinstance(
                trigger_operator, str
            ):
                raise ValueError(
                    f"emotions.{name}.triggerOperator must be a string"
                )
            updates.append(
                (
                    name,
                    float(value),
                    triggered,
                    trigger_threshold,
                    trigger_operator,
                )
            )

        for update in updates:
            self._blackboard.emotion_module.update_state(*update)
            emotion_name, _, triggered, _, _ = update
            if not triggered:
                self._invalidate_emotion_visual_request(emotion_name)
                self._candidate_pool.discard_emotion(emotion_name)
                self._stop_emotion_continuation(emotion_name)
                self._pending_emotion_edges.pop(emotion_name, None)
                self._pending_emotion_retry_at.pop(emotion_name, None)

        emotion_names = (
            "Joy", "Excite", "Anxiety", "Fear", "Curious", "Calm",
        )
        log_state = tuple(
            (
                name,
                self._blackboard.emotion_module.is_triggered(name),
            )
            for name in emotion_names
        )
        if log_state != self._last_logged_emotion_state:
            states = ", ".join(
                f"{name}={'on' if triggered else 'off'}"
                for name, triggered in log_state
            )
            self._logger.debug(f"/emotion/state changed: [{states}]")
            self._last_logged_emotion_state = log_state
    except Exception as e:
        self._logger.error(f"Failed to parse /emotion/state: {e}")


def on_emotion_signal_ros2(self, msg):
    """Handle /emotion/signal_event (event-driven).

    Accepts only V2 single-threshold upward-edge events.
    """
    try:
        data = json.loads(msg.data)
        if data.get("schema_version") != "2.0":
            raise ValueError(
                "unsupported emotion schema_version "
                f"{data.get('schema_version')!r}; expected '2.0'"
            )

        event_type = data.get("event_type")
        expected_emotion = EMOTION_V2_EVENT_TO_NAME.get(event_type)
        if expected_emotion is None:
            raise ValueError(f"unsupported V2 emotion event {event_type!r}")

        emotion_name = data.get("emotion")
        if emotion_name != expected_emotion:
            raise ValueError(
                f"event {event_type} requires emotion={expected_emotion!r}, "
                f"got {emotion_name!r}"
            )

        signal_value = data.get("value")
        if (
            isinstance(signal_value, bool)
            or not isinstance(signal_value, (int, float))
        ):
            raise ValueError("emotion signal value must be numeric")
        trigger_threshold = data.get("triggerThreshold")
        if (
            trigger_threshold is not None
            and (
                isinstance(trigger_threshold, bool)
                or not isinstance(trigger_threshold, (int, float))
            )
        ):
            raise ValueError("emotion signal triggerThreshold must be numeric")
        trigger_operator = data.get("triggerOperator")
        if trigger_operator is not None and not isinstance(
            trigger_operator,
            str,
        ):
            raise ValueError("emotion signal triggerOperator must be a string")

        # candidate_inject/select/start are the INFO-level audit trail. The
        # raw ingress record remains available at DEBUG for contract checks.
        self._logger.debug(f"/emotion/signal_event: {event_type}")

        # Bridge the gap before the next 1Hz state snapshot. Recovery is
        # still authoritative from /emotion/state.triggered=false.
        self._blackboard.emotion_module.update_state(
            emotion_name,
            float(signal_value),
            True,
            trigger_threshold,
            trigger_operator,
        )
        self._start_emotion_continuation(emotion_name)
        self._invalidate_emotion_visual_request(emotion_name)
        self._request_contextual_emotion_candidate(
            emotion_name,
            trigger_event=event_type,
        )
    except Exception as e:
        self._logger.error(f"Failed to parse /emotion/signal_event: {e}")


def on_need_state_ros2(self, msg):
    """Handle authoritative ``/internal_need/state`` V2 snapshots."""
    try:
        data = json.loads(msg.data)
        if data.get("schema_version") != "2.0":
            raise ValueError(
                "unsupported internal need schema_version "
                f"{data.get('schema_version')!r}; expected '2.0'"
            )

        demands = data.get("demands")
        if not isinstance(demands, dict):
            raise ValueError("demands must be an object")

        updates = []
        for need_name, need_info in demands.items():
            if need_name not in NEED_V2_ACTIVE_LEVELS:
                raise ValueError(f"unknown demand {need_name!r}")
            if not isinstance(need_info, dict):
                raise ValueError(f"demands.{need_name} must be an object")

            context = f"demands.{need_name}"
            value = need_info.get("value")
            if not _is_json_number(value):
                raise ValueError(f"{context}.value must be numeric")
            if not 0 <= float(value) <= 100:
                raise ValueError(f"{context}.value must be within 0..100")

            thresholds = _parse_need_thresholds(
                need_info,
                context,
                require_overflow_operator=False,
            )
            (
                trigger_threshold,
                trigger_operator,
                urgent_threshold,
                urgent_operator,
                overflow_threshold,
                overflow_operator,
            ) = thresholds

            level = need_info.get("level")
            allowed_levels = (
                {NEED_LEVEL_NORMAL}
                | set(NEED_V2_ACTIVE_LEVELS[need_name])
            )
            if level not in allowed_levels:
                raise ValueError(
                    f"{context}.level {level!r} is not configured"
                )
            computed_level = _need_level_from_value(
                float(value),
                trigger_threshold=trigger_threshold,
                urgent_threshold=urgent_threshold,
                overflow_threshold=overflow_threshold,
            )
            if level != computed_level:
                raise ValueError(
                    f"{context}.level must be {computed_level!r} "
                    f"for value {value!r}"
                )

            expected_event = _need_level_event(need_name, level)
            level_event = need_info.get("levelEvent")
            if level_event != expected_event:
                raise ValueError(
                    f"{context}.levelEvent must be {expected_event!r}"
                )

            expected_triggered = level != NEED_LEVEL_NORMAL
            expected_urgent = (
                urgent_threshold is not None
                and level in (NEED_LEVEL_URGENT, NEED_LEVEL_OVERFLOW)
            )
            expected_overflow = level == NEED_LEVEL_OVERFLOW
            flags = {
                "triggered": expected_triggered,
                "urgent": expected_urgent,
                "overflow": expected_overflow,
                "levelActive": expected_triggered,
            }
            for field, expected in flags.items():
                actual = need_info.get(field)
                if not isinstance(actual, bool) or actual is not expected:
                    raise ValueError(
                        f"{context}.{field} must be {expected!r}"
                    )

            # A configured level and its threshold metadata must agree.
            has_urgent_level = NEED_LEVEL_URGENT in NEED_V2_ACTIVE_LEVELS[
                need_name
            ]
            has_overflow_level = (
                NEED_LEVEL_OVERFLOW in NEED_V2_ACTIVE_LEVELS[need_name]
            )
            if has_urgent_level != (urgent_threshold is not None):
                raise ValueError(
                    f"{context} urgent threshold configuration mismatch"
                )
            if has_overflow_level != (overflow_threshold is not None):
                raise ValueError(
                    f"{context} overflow threshold configuration mismatch"
                )

            updates.append({
                "name": need_name,
                "value": float(value),
                "trigger_threshold": trigger_threshold,
                "trigger_operator": trigger_operator,
                "urgent_threshold": urgent_threshold,
                "urgent_operator": urgent_operator,
                "overflow_threshold": overflow_threshold,
                "overflow_operator": overflow_operator,
                "triggered": expected_triggered,
                "urgent": expected_urgent,
                "overflow": expected_overflow,
                "level": level,
                "level_event": level_event,
                "level_active": expected_triggered,
            })

        # Validate the full snapshot before applying any entry.
        for update in updates:
            existing = self._blackboard.need_module.get_need(update["name"])
            existing_event = existing.level_event if existing else None
            self._blackboard.need_module.update_state(**update)
            if existing_event != update["level_event"]:
                self._invalidate_need_visual_request(update["name"])
            self._candidate_pool.discard_need_except(
                update["name"],
                update["level_event"],
            )

        need_names = (
            "Hunger", "Bladder", "Sleepiness", "Cleanliness",
            "Energy", "Social", "Exploration",
        )
        log_state = tuple(
            (
                name,
                self._blackboard.need_module.level_events.get(name, "?"),
            )
            for name in need_names
        )
        if log_state != self._last_logged_need_state:
            events = ", ".join(
                f"{name}={event}" for name, event in log_state
            )
            self._logger.debug(
                f"/internal_need/state changed: [{events}]"
            )
            self._last_logged_need_state = log_state
    except Exception as e:
        self._logger.error(f"Failed to parse /internal_need/state: {e}")


def on_need_signal_ros2(self, msg):
    """Handle exact V2 need level-change events."""
    try:
        data = json.loads(msg.data)
        if data.get("schema_version") != "2.0":
            raise ValueError(
                "unsupported internal need schema_version "
                f"{data.get('schema_version')!r}; expected '2.0'"
            )

        event_type = data.get("event_type")
        expected_state = NEED_V2_EVENT_TO_STATE.get(event_type)
        if expected_state is None:
            raise ValueError(f"unsupported V2 need event {event_type!r}")

        demand = data.get("demand")
        level = data.get("level")
        expected_demand, expected_level = expected_state
        if demand != expected_demand or level != expected_level:
            raise ValueError(
                f"event {event_type} requires demand={expected_demand!r}, "
                f"level={expected_level!r}; got {demand!r}/{level!r}"
            )

        value = data.get("value")
        if not _is_json_number(value):
            raise ValueError("need signal value must be numeric")
        if not 0 <= float(value) <= 100:
            raise ValueError("need signal value must be within 0..100")

        previous_level = data.get("previousLevel")
        if previous_level not in {
            NEED_LEVEL_NORMAL,
            *NEED_V2_ACTIVE_LEVELS[demand],
        }:
            raise ValueError(
                f"invalid previousLevel {previous_level!r} for {demand}"
            )
        if previous_level == level:
            raise ValueError(
                "need signal previousLevel must differ from current level"
            )
        if data.get("trigger") != "LEVEL_CHANGED":
            raise ValueError("need signal trigger must be 'LEVEL_CHANGED'")

        thresholds = _parse_need_thresholds(
            data,
            "need signal",
            require_overflow_operator=True,
        )
        (
            trigger_threshold,
            trigger_operator,
            urgent_threshold,
            urgent_operator,
            overflow_threshold,
            overflow_operator,
        ) = thresholds

        has_urgent_level = NEED_LEVEL_URGENT in NEED_V2_ACTIVE_LEVELS[demand]
        has_overflow_level = (
            NEED_LEVEL_OVERFLOW in NEED_V2_ACTIVE_LEVELS[demand]
        )
        if has_urgent_level != (urgent_threshold is not None):
            raise ValueError("need signal urgent threshold configuration mismatch")
        if has_overflow_level != (overflow_threshold is not None):
            raise ValueError("need signal overflow threshold configuration mismatch")
        computed_level = _need_level_from_value(
            float(value),
            trigger_threshold=trigger_threshold,
            urgent_threshold=urgent_threshold,
            overflow_threshold=overflow_threshold,
        )
        if level != computed_level:
            raise ValueError(
                f"need signal level must be {computed_level!r} "
                f"for value {value!r}"
            )

        self._logger.debug(
            f"/internal_need/signal_event: {event_type} demand={demand} level={level}")

        triggered = level != NEED_LEVEL_NORMAL
        urgent = (
            urgent_threshold is not None
            and level in (NEED_LEVEL_URGENT, NEED_LEVEL_OVERFLOW)
        )
        overflow = level == NEED_LEVEL_OVERFLOW
        self._blackboard.need_module.update_state(
            demand,
            value=float(value),
            trigger_threshold=trigger_threshold,
            trigger_operator=trigger_operator,
            urgent_threshold=urgent_threshold,
            urgent_operator=urgent_operator,
            overflow_threshold=overflow_threshold,
            overflow_operator=overflow_operator,
            triggered=triggered,
            urgent=urgent,
            overflow=overflow,
            level=level,
            level_event=event_type,
            level_active=triggered,
            previous_level=previous_level,
        )
        self._invalidate_need_visual_request(demand)
        self._candidate_pool.discard_need_except(demand, event_type)

        if triggered:
            if demand in ("Hunger", "Social", "Exploration"):
                self._request_contextual_need_candidate(
                    demand,
                    float(value),
                    trigger_event=event_type,
                    level=level,
                )
            else:
                self._generate_need_candidate(
                    demand,
                    float(value),
                    trigger_event=event_type,
                    level=level,
                )
    except Exception as e:
        self._logger.error(f"Failed to parse /internal_need/signal_event: {e}")
