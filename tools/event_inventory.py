"""Build/check an offline event view. Never dispatch events or import a runtime."""
from __future__ import annotations

import ast
import math
from pathlib import Path

CODE_SOURCES = (
    "modules/behavior/marsdog_behavior/intent_mapper.py",
    "modules/behavior/marsdog_behavior/voice_engagement_coordinator.py",
)


def route_id(row):
    return "|".join((row["source"], row["event"], row["context"]))


def policy(entry):
    # Absent values mean runtime defaults, not values invented by this inventory.
    return {key: value for key, value in entry.items() if key != "routes"}


def symbol_exists(root, path, symbol):
    body = ast.parse((root / path).read_bytes()).body
    for part in symbol.split("."):
        node = next((n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef,
                    ast.AsyncFunctionDef)) and n.name == part), None)
        if node is None:
            return False
        body = node.body
    return True


def event_index(catalog):
    events = {}

    def get(event):
        return events.setdefault(event, {"event": event, "direct_paths": [],
                                        "internal_paths": [], "emotion_rule": None})

    all_routes = catalog["routes"] + catalog["tactile_routes"] + catalog["reaction_routes"]
    for row in all_routes:
        kind = "internal_paths" if row["source"] in {"need", "emotion"} else "direct_paths"
        get(row["event"])[kind].append(route_id(row))
    for row in catalog["code_entrypoints"]:
        for event in row["events"]:
            get(event)["direct_paths"].append("code|" + row["id"])
    for event, rule in catalog["emotion_effects"].items():
        get(event)["emotion_rule"] = rule
    for row in catalog["voice_commands"]:
        get(row["event"])
    for row in events.values():
        direct, internal, state = bool(row["direct_paths"]), bool(row["internal_paths"]), row["emotion_rule"] is not None
        row["classification"] = ("direct_and_emotion" if direct and state else
                                 "direct_only" if direct else "emotion_only" if state else
                                 "internal_trigger" if internal else "unmapped_in_scope")
        row["direct_paths"].sort()
        row["internal_paths"].sort()
    return [events[event] for event in sorted(events)]


def extend(root, data, catalog):
    tactile = data["tactile"]
    emotion = data["emotion_effects"]["emotions"]
    paths = data["runtime_entries"]
    if paths["schema_version"] != 1:
        raise ValueError("unsupported runtime entry index")
    for entry in paths["entries"]:
        if entry["source"] != "audio_session":
            raise ValueError("new runtime entry source requires extraction review")
        for ref in entry["code"]:
            if ref["path"] not in CODE_SOURCES or not symbol_exists(root, ref["path"], ref["symbol"]):
                raise ValueError("runtime entry symbol missing: " + str(ref))
    catalog.update(event_routing_version=1, tactile_routes=[], reaction_routes=[],
                   code_entrypoints=paths["entries"], emotion_effects=emotion["eventRules"],
                   emotion_types=sorted(emotion["types"]),
                   category_policies=data["categories"]["categories"],
                   emotion_deduplication_window_sec=emotion.get("eventDeduplicationWindowSeconds"),
                   tactile_policy={key: value for key, value in tactile.items() if key != "events"},
                   route_policies={})
    for row in catalog["routes"]:
        if row["source"] == "emotion":
            base = data["emotions"]["emotion_behavior_map"][row["event"]]
            overlay = base["routes"][row["context"].split("/")[0]]
        else:
            base = data["events"][row["source"]][row["event"]]
            overlay = base.get("routes", {}).get(row["context"], {})
        catalog["route_policies"][route_id(row)] = policy({**base, **overlay})
    for event, entry in sorted(tactile["events"].items()):
        catalog["tactile_routes"].append({
            "source": "touch_direct", "event": event, "context": "STARTED",
            "enabled": tactile["enabled"], "executor_behaviors": [entry["behavior_name"]],
            "configured_policy": policy(entry), "owner_role": "BehaviorTree",
        })
    emotion_routes = data["emotions"]["emotion_behavior_map"]
    for event, entry in sorted(data["events"]["audio_reaction"].items()):
        for reaction in entry["reactions"]:
            trigger = "EMO_" + reaction["emotion"].upper() + "_TRIGGERED"
            for context, route in emotion_routes[trigger]["routes"].items():
                if context not in {"human", "solo"}:
                    raise ValueError("new social reaction context requires extraction review")
                for key in ("behavior_name", "voice_waiting_behavior_name"):
                    if key not in route or key == "voice_waiting_behavior_name" and context != "human":
                        continue
                    catalog["reaction_routes"].append({
                        "source": "audio_reaction", "event": event,
                        "context": reaction["emotion"] + "/" + context + ("/voice_waiting" if key.startswith("voice_waiting") else ""),
                        "executor_behaviors": [route[key]], "emotion_style": reaction["emotion"],
                        "weight": reaction.get("weight", 1.0), "configured_policy": policy(entry),
                        "selection": "weighted_emotion_then_context", "owner_role": "BehaviorTree",
                    })
    catalog["event_index"] = event_index(catalog)
    catalog["coverage"] = {
        "scope": "Configured reactions, emotion influence, internal triggers and explicitly indexed runtime entries",
        "code_paths_exhaustive": False,
        "defaults": "Absent policy values remain runtime defaults; this view does not execute mapping logic",
        "dual_path": "Independent consumers; immediate reaction and later internal expression require scenario-specific review",
    }
    return catalog


def finite_number(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def valid_rank(value):
    return (type(value) is int and value >= 0 or
            isinstance(value, str) and value.isascii() and value.isdigit())


def analyze(catalog):
    """Offline consistency checks; never change a runtime policy or legacy exception."""
    if catalog.get("event_routing_version") != 1:
        return ["event routing inventory missing; refresh with the current extractor"]
    from capability_decisions import validate_decisions
    errors, seen = validate_decisions(catalog), set()
    templates = catalog["behaviors"]
    for row in catalog["tactile_routes"] + catalog["reaction_routes"]:
        key = route_id(row)
        if key in seen:
            errors.append("duplicate supplemental route: " + key)
        seen.add(key)
        if not row["executor_behaviors"]:
            errors.append("empty supplemental route: " + key)
        for name in row["executor_behaviors"]:
            if name not in templates:
                errors.append("missing supplemental template: " + key + " -> " + name)
        if row["source"] == "audio_reaction" and not finite_number(row["weight"], positive=True):
            errors.append("invalid reaction weight: " + key)
        if row["source"] == "touch_direct":
            if not row["event"].startswith("EVT_TACTILE_") or type(row["enabled"]) is not bool:
                errors.append("invalid tactile event/enabled: " + key)
            p = row["configured_policy"]
            if not valid_rank(p.get("priority_level", 1)) or not 1 <= int(p.get("priority_level", 1)) <= 6:
                errors.append("invalid tactile priority: " + key)
            for field in ("ttl_sec", "timeout_sec", "cooldown_sec"):
                if not finite_number(p.get(field), positive=True):
                    errors.append("invalid tactile " + field + ": " + key)
            if p.get("interrupt_policy") not in {"safe_point", "immediate", "non_interruptible"}:
                errors.append("invalid tactile interrupt policy: " + key)
    all_policies = list(catalog["route_policies"].items()) + [(route_id(r), r["configured_policy"])
                   for r in catalog["tactile_routes"] + catalog["reaction_routes"]]
    for key, configured in all_policies:
        policies = [configured]
        if isinstance(configured.get("params"), dict):
            policies.append(configured["params"])
        for values in policies:
            for field in ("priority_level", "sub_priority", "semantic_rank", "modality_rank", "behavior_rank"):
                if field in values and not valid_rank(values[field]):
                    errors.append("invalid integer rank: " + key + ": " + field)
    known_types = set(catalog["emotion_types"])
    for event, rule in catalog["emotion_effects"].items():
        if not event.startswith("EVT_") or not isinstance(rule.get("deltas"), dict):
            errors.append("invalid emotion event rule: " + event)
            continue
        for name, delta in rule["deltas"].items():
            if name not in known_types or type(delta) not in (int, float) or not math.isfinite(delta):
                errors.append("invalid emotion delta: " + event + ": " + name)
    ids = set()
    for entry in catalog["code_entrypoints"]:
        if entry["id"] in ids or not entry["events"] or not entry["executor_behaviors"] or not entry["code"]:
            errors.append("invalid runtime entry: " + entry["id"])
        ids.add(entry["id"])
        for name in entry["executor_behaviors"]:
            if name not in templates:
                errors.append("missing runtime entry template: " + name)
    if set(catalog["route_policies"]) != {route_id(row) for row in catalog["routes"]}:
        errors.append("route policy coverage differs from declared routes")
    if catalog["event_index"] != event_index(catalog):
        errors.append("event index differs from owning rules")
    tactile = catalog["tactile_policy"]
    if type(tactile.get("enabled")) is not bool:
        errors.append("tactile enabled must be boolean")
    for key, default in (("max_age_sec", 2.0), ("future_tolerance_sec", 0.5)):
        if not finite_number(tactile.get(key, default), positive=True):
            errors.append("invalid tactile " + key)
    return errors
