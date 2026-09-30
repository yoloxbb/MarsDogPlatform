"""Extract a reviewable identifier graph from owning YAML configs; no business imports.

Only this refresh worker needs PyYAML, supplied by an existing module environment.
The normal checker and CI boundary job remain standard-library-only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "events": "modules/behavior/config/event_intent_map.yaml",
    "pools": "modules/behavior/config/intent_action_pool.yaml",
    "categories": "modules/behavior/config/behavior_categories.yaml",
    "emotions": "modules/behavior/config/emotion_behavior_map.yaml",
    "voice": "modules/voice/config/command_catalog.yaml",
    "templates": "modules/action/config/behavior_tree_actions.yaml",
    "units": "modules/action/config/action_catalog.yaml",
}
FINGERPRINT_PATHS = (*SOURCES.values(), "tools/identifier_catalog.py")


def fingerprints(root: Path) -> dict:
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in FINGERPRINT_PATHS}


def read_yaml(path: Path):
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in seen:
                    raise ValueError(f"{path}:{key_node.start_mark.line + 1}: duplicate YAML key {key!r}")
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def collect(root: Path) -> dict:
    data = {name: read_yaml(root / path) for name, path in SOURCES.items()}
    events, pools = data["events"], data["pools"]
    # Explicit failure prevents a new source family from being silently omitted.
    if set(events) != {"audio_direct", "audio_reaction", "visual_direct", "need", "emotion"}:
        raise ValueError("event source families changed; update catalog extraction coverage")
    routes = []
    for source in ("audio_direct", "visual_direct", "need"):
        for event, base in events[source].items():
            for context, overlay in (base.get("routes") or {"default": {}}).items():
                entry = {**base, **overlay}
                intent = entry.get("intent", "")
                direct = entry.get("behavior_name")
                names = [direct] if direct else pools.get(intent, {}).get("candidates", [])
                executor = entry.get("params", {}).get("executor_behavior_name")
                routes.append({
                    "source": source, "event": event, "context": context,
                    "category": entry["category"], "intent": intent,
                    "selection": "explicit_behavior" if direct else "intent_pool",
                    "expected_command_id": entry.get("expected_command_id"),
                    "bt_behaviors": names,
                    "executor_behaviors": [executor or name for name in names],
                })

    emotions = data["emotions"]["emotion_behavior_map"]
    if set(emotions) != set(events["emotion"]):
        raise ValueError("emotion event registry and route definitions disagree")
    for event, entry in emotions.items():
        for context, route in entry["routes"].items():
            for field in ("behavior_name", "voice_waiting_behavior_name"):
                if field in route:
                    routes.append({
                        "source": "emotion", "event": event,
                        "context": context + ("/voice_waiting" if field.startswith("voice_waiting") else ""),
                        "category": events["emotion"][event]["category"],
                        "intent": entry["intent"], "selection": "explicit_behavior",
                        "expected_command_id": None, "bt_behaviors": [route[field]],
                        "executor_behaviors": [route[field]],
                    })

    behaviors = {}
    for name, template in data["templates"]["behaviors"].items():
        if template.get("behavior_name") != name:
            raise ValueError(f"behavior key/name mismatch: {name}")
        behaviors[name] = [{
            "stage_id": stage["stage_id"],
            "units": [item if isinstance(item, str) else item["unit_id"]
                      for item in stage["candidates"]],
        } for stage in template["stages"]]
    units = data["units"]["action_units"]
    for name, unit in units.items():
        if unit.get("unit_id") != name:
            raise ValueError(f"unit key/id mismatch: {name}")

    # Product labels have their own namespace even when they start with ACT_.
    voice_commands = [{
        "command_key": item["command_key"], "command_id": item["command_id"],
        "event": item["event_type"], "product_action_label": item.get("action_name", ""),
    } for item in data["voice"]["commands"]]
    return {
        "schema_version": 1,
        "source_sha256": fingerprints(root),
        "categories": sorted(data["categories"]["categories"]),
        "pools": {name: entry["candidates"] for name, entry in pools.items()},
        "routes": routes,
        "social_reactions": [{
            "event": event, "intent": entry["intent"], "category": entry["category"],
            "expected_command_id": entry["expected_command_id"],
            "emotion_events": ["EMO_" + item["emotion"].upper() + "_TRIGGERED"
                               for item in entry["reactions"]],
        } for event, entry in events["audio_reaction"].items()],
        "voice_commands": voice_commands,
        "behaviors": behaviors,
        "units": sorted(units),
    }


if __name__ == "__main__":
    print(json.dumps(collect(ROOT), indent=2, ensure_ascii=False))
