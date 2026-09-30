"""Check naming and declared Voice -> BT -> Action references without loading runtimes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from identifier_catalog import ROOT, fingerprints
from runtime_environment import clean_environment

CATALOG = "interfaces/naming/catalog.json"
EXCEPTIONS = "interfaces/naming/compatibility_exceptions.json"
PATTERNS = {
    "event": r"(?:EVT|NEED|EMO)_[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*",
    "intent": r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*",
    "behavior": r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*",
    "unit": r"ACT_[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*",
    "command": r"CMD_[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*",
    "product_action_label": r"ACT_[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*",
}


def gap_key(row, behavior):
    return "|".join((row["source"], row["event"], row["context"], behavior))


def analyze(catalog):
    """Return errors and exact legacy findings; never infer robot capabilities."""
    if catalog["schema_version"] != 1:
        raise ValueError("unsupported catalog schema")
    errors, missing, ids = [], set(), {key: set() for key in PATTERNS}
    templates = catalog["behaviors"]
    ids["behavior"].update(templates)
    ids["unit"].update(catalog["units"])
    used_pools = set()
    route_keys = set()
    for intent, names in catalog["pools"].items():
        ids["intent"].add(intent)
        ids["behavior"].update(names)
        if not names:
            errors.append(f"empty intent pool: {intent}")
    for row in catalog["routes"]:
        key = (row["source"], row["event"], row["context"])
        if key in route_keys:
            errors.append(f"duplicate route: {key}")
        route_keys.add(key)
        ids["event"].add(row["event"])
        ids["intent"].add(row["intent"])
        ids["behavior"].update(row["bt_behaviors"])
        ids["behavior"].update(row["executor_behaviors"])
        if row["category"] not in catalog["categories"]:
            errors.append(f"unknown category: {key}: {row['category']}")
        if not row["bt_behaviors"] or not row["executor_behaviors"]:
            errors.append(f"empty behavior route: {key}")
        if row["selection"] == "intent_pool":
            used_pools.add(row["intent"])
            if catalog["pools"].get(row["intent"]) != row["bt_behaviors"]:
                errors.append(f"unknown or inconsistent intent pool: {key}")
        elif row["selection"] != "explicit_behavior":
            errors.append(f"unknown selection mode: {key}")
        for name in row["executor_behaviors"]:
            if name not in templates:
                missing.add(gap_key(row, name))

    emotion_events = {r["event"] for r in catalog["routes"] if r["source"] == "emotion"}
    for row in catalog["social_reactions"]:
        ids["event"].add(row["event"])
        ids["intent"].add(row["intent"])
        if row["category"] not in catalog["categories"]:
            errors.append(f"unknown social category: {row['event']}")
        for event in row["emotion_events"]:
            if event not in emotion_events:
                errors.append(f"social reaction missing emotion route: {row['event']} -> {event}")

    voice_by_event = {}
    for field in ("command_key", "command_id", "event"):
        values = [r[field] for r in catalog["voice_commands"]]
        if len(values) != len(set(values)):
            errors.append(f"duplicate voice {field}")
    for row in catalog["voice_commands"]:
        voice_by_event[row["event"]] = row
        ids["event"].add(row["event"])
        ids["command"].add(row["command_id"])
        if row["product_action_label"]:
            ids["product_action_label"].add(row["product_action_label"])
    audio = [r for r in catalog["routes"] if r["source"] == "audio_direct"]
    audio += catalog["social_reactions"]
    non_catalog_audio_routes = set()
    for row in audio:
        expected = row["expected_command_id"]
        if not expected and row["event"] != "EVT_VOICE_WAKEUP":
            errors.append(f"missing expected_command_id: {row['event']}")
        if expected:
            ids["command"].add(expected)
            producer = voice_by_event.get(row["event"])
            if not producer:
                non_catalog_audio_routes.add(row["event"] + "|" + expected)
            elif producer["command_id"] != expected:
                errors.append(f"voice/BT command_id mismatch: {row['event']}: {expected}")
    voice_without_route = set(voice_by_event) - {r["event"] for r in audio}

    for name, stages in templates.items():
        if not stages:
            errors.append(f"empty action template: {name}")
        stage_ids = [s["stage_id"] for s in stages]
        if len(stage_ids) != len(set(stage_ids)):
            errors.append(f"duplicate stage_id: {name}")
        for stage in stages:
            if not stage["units"]:
                errors.append(f"empty stage: {name}/{stage['stage_id']}")
            for unit in stage["units"]:
                ids["unit"].add(unit)
                if unit not in catalog["units"]:
                    errors.append(f"unknown action unit: {name}/{stage['stage_id']} -> {unit}")
    noncanonical = {f"{kind}|{name}" for kind, names in ids.items()
                    for name in names if not re.fullmatch(PATTERNS[kind], name)}
    return {
        "errors": errors,
        "missing_templates": sorted(missing),
        "legacy_spellings": sorted(noncanonical),
        "voice_without_route": sorted(voice_without_route),
        "non_catalog_audio_routes": sorted(non_catalog_audio_routes),
        "pools_not_selected_by_declared_routes": sorted(set(catalog["pools"]) - used_pools),
    }


def validate(catalog, exceptions):
    findings = analyze(catalog)
    errors = list(findings["errors"])
    if exceptions["schema_version"] != 1:
        errors.append("unsupported exception schema")
    for key in ("missing_templates", "legacy_spellings", "voice_without_route", "non_catalog_audio_routes"):
        registered = exceptions[key]
        if len(registered) != len(set(registered)):
            errors.append(f"duplicate exceptions: {key}")
        actual, accepted = set(findings[key]), set(registered)
        errors += [f"unregistered {key}: {item}" for item in sorted(actual - accepted)]
        errors += [f"stale {key} exception (remove after review): {item}"
                   for item in sorted(accepted - actual)]
    return {
        "status": "FAIL" if errors else ("PASS_WITH_KNOWN_GAPS" if findings["missing_templates"] else "PASS"),
        "errors": errors,
        "counts": {
            "declared_event_routes": len(catalog["routes"]),
            "voice_commands": len(catalog["voice_commands"]),
            "intent_pools": len(catalog["pools"]),
            "action_templates": len(catalog["behaviors"]),
            "action_units": len(catalog["units"]),
            "known_missing_template_routes": len(findings["missing_templates"]),
            "voice_events_without_declared_route": len(findings["voice_without_route"]),
            "non_catalog_audio_routes": len(findings["non_catalog_audio_routes"]),
        },
        "findings": {key: value for key, value in findings.items() if key != "errors"},
        "scope": "Declared default YAML graph only; no execution/hardware/ASR accuracy claims. "
                 "Code-only, conditional authorization and deployed override paths need runtime contracts.",
    }


def check_freshness(catalog, root):
    if catalog["source_sha256"] != fingerprints(root):
        raise ValueError("catalog sources changed; run check_identifiers.py --refresh --python <module-python>")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="Regenerate catalog; never grow exceptions")
    mode.add_argument("--live", action="store_true", help="Reparse YAML and verify committed catalog")
    parser.add_argument("--python", type=Path, help="Existing module Python with PyYAML; no runtime imports")
    parser.add_argument("--output", type=Path, default=ROOT / "out/identifiers/result.json")
    args = parser.parse_args()
    try:
        if args.refresh or args.live:
            if not args.python:
                parser.error("--refresh/--live requires --python (e.g. modules/action/.venv/bin/python)")
            run = subprocess.run(
                [str(args.python.resolve()), "-B", str(ROOT / "tools/identifier_catalog.py")],
                cwd=ROOT, env=clean_environment(), text=True, capture_output=True, timeout=60)
            if run.returncode:
                raise ValueError(run.stderr.strip())
            catalog = json.loads(run.stdout)
        else:
            catalog = json.loads((ROOT / CATALOG).read_text())
        check_freshness(catalog, ROOT)
        report = validate(catalog, json.loads((ROOT / EXCEPTIONS).read_text()))
        if args.live and catalog != json.loads((ROOT / CATALOG).read_text()):
            report["errors"].append("committed catalog differs from live extraction")
            report["status"] = "FAIL"
        if args.refresh and not report["errors"]:
            (ROOT / CATALOG).write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        report = {"status": "FAIL", "errors": [str(error)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "findings"},
                     indent=2, ensure_ascii=False))
    return int(report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
