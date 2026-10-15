"""Behavior decision events; observation never participates in arbitration."""
from marsdog_observability import emit as observe, enabled
from bionic_dog_bt.drive_policy import resolve_drive
_FIELDS = ("interaction_id", "utterance_id", "wake_id", "event_type", "trigger_event",
           "command_id", "intent", "source", "behavior_name", "candidate_id",
           "behavior_id", "goal_id", "priority_level", "value", "status", "result", "reason")


def emit(stage, item=None, *, repeat_key=None, **details):
    if not enabled():
        return
    try:
        get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
        params = get("params", {}) or {}
        if not isinstance(params, dict):
            params = {}
        fields = {key: get(key, params.get(key)) for key in _FIELDS
                  if isinstance(get(key, params.get(key)), (str, int, float, bool))}
        fields.update(details)
        # Derived observation only: never add ownership hints to Goal payloads
        # or let caller-provided diagnostic fields choose a drive policy.
        drive_params = dict(params)
        if isinstance(get("source"), str):
            drive_params.setdefault("source", get("source"))
        policy = resolve_drive(drive_params, get("need_type", ""))
        if policy.drive is not None:
            fields.update(behavior_drive=policy.drive.value,
                          state_domain=policy.state_domain,
                          legacy_drive=policy.legacy)
        observe("behavior." + stage.replace("_", "."), fields, repeat_key=repeat_key,
                kind="lifecycle" if stage in {"goal_dispatch", "goal_accepted", "bt_terminal", "action_terminal"} else "event")
    except Exception:
        # No diagnostic failure may mutate queue/goal ownership.
        return
