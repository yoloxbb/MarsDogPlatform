"""Versioned configuration snapshots and evidence references, not robot acceptance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from event_inventory import route_id

REPORT_STATUSES = {"PASS", "PASS_WITH_EXPLICIT_LIMITS", "PASS_WITH_KNOWN_GAPS", "FAIL",
                   "SKIP", "NOT_RUN", "RUNNING", "NOT_RECORDED"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def describe_route(row, action, *, identity=None):
    names = row["executor_behaviors"]
    missing = [name for name in names if name not in action["behaviors"]]
    states = [action["behaviors"][name]["configuration_status"] for name in names if name not in missing]
    status = ("missing_template" if missing else "blocked" if row.get("enabled") is False or
              states and all(s == "blocked" for s in states) else "runtime_check_required")
    return {**row, "capability_id": identity or route_id(row), "missing_templates": missing,
            "configuration_status": status,
            "acceptance": {"software": "NOT_RECORDED", "board": "NOT_RECORDED", "hardware": "NOT_RECORDED"}}


def supplement(catalog, action):
    rows = [describe_route(row, action) for row in catalog.get("tactile_routes", []) + catalog.get("reaction_routes", [])]
    for entry in catalog.get("code_entrypoints", []):
        rows.append(describe_route(entry, action, identity="code|" + entry["id"]))
    return rows


def evidence_references(paths, root):
    references = []
    seen = set()
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("validation report must be a file inside this checkout")
        if path in seen:
            raise ValueError("duplicate validation report")
        seen.add(path)
        data = path.read_bytes()
        if len(data) > 2_000_000:
            raise ValueError("validation report too large")
        report = json.loads(data)
        if not isinstance(report, dict) or not isinstance(report.get("status"), str) or report["status"] not in REPORT_STATUSES:
            raise ValueError("validation report requires an explicit supported status: " + str(path))
        references.append({"path": path.relative_to(root.resolve()).as_posix(),
                           "sha256": hashlib.sha256(data).hexdigest(), "reported_status": report["status"],
                           "scope": report.get("scope"), "binding": "reference_only_not_capability_acceptance"})
    return references


def source_revision(root):
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                      stderr=subprocess.DEVNULL, text=True).strip()
        if Path(top).resolve() != root.resolve():
            return {"head": None, "dirty": None, "reason": "snapshot_directory_not_repository_root"}
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root))
        return {"head": head, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "dirty": None, "reason": "git_unavailable"}


def release_manifest(value, capability_bytes, root, references):
    rows = value["routes"] + value["supplemental_routes"]
    return {
        "schema_version": 1, "status": "CONFIGURATION_SNAPSHOT", "release_acceptance": "NOT_ASSESSED",
        "capabilities_sha256": hashlib.sha256(capability_bytes).hexdigest(),
        "source_revision": source_revision(root), "catalog_source_sha256": value["catalog_source_sha256"],
        "selected_configuration": {key: value["action"].get(key) for key in
                                   ("chassis", "runtime_overrides", "config_dir", "config_sha256")},
        "tool_sha256": {str(p): sha256(root / p) for p in ("tools/capabilities.py", "tools/capability_snapshot.py",
                       "modules/action/marsdog_action_executor/capability_report.py")},
        "module_lock_sha256": {name: sha256(root / "modules" / name / "uv.lock")
                               for name in ("action", "behavior", "emotion", "vision", "voice")},
        "counts": {"declared_routes": len(value["routes"]), "supplemental_entries": len(value["supplemental_routes"]),
                   "missing_template_routes": sum(bool(r["missing_templates"]) for r in rows)},
        "validation_reports": references,
        "limits": ["Report references are not bound to individual capabilities or this source revision.",
                   "Configuration state, software evidence, board deployment and hardware acceptance remain separate.",
                   "Missing templates retain explicit decisions and dependencies when registered; this tool creates no actions and retires no routes."],
    }


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def event_markdown(value):
    labels = {"direct_only": "仅直驱", "emotion_only": "仅影响情绪", "direct_and_emotion": "双路径",
              "internal_trigger": "内部触发", "unmapped_in_scope": "本范围未配置反应"}
    lines = ["# 事件分流清单", "", "从各领域配置生成，分类表示配置路径；不表示硬件已接入或此事件必然执行行为。",
             "情绪增量只更新状态，达到阈值后才可能产生内部候选。空缺策略使用运行时默认，本清单不另造默认值。", "",
             "| 事件 | 配置路径 | 候选路径 ID | 基础情绪影响 |", "| --- | --- | --- | --- |"]
    for row in value.get("event_index", []):
        influence = (row["emotion_rule"] or {}).get("deltas", {})
        cells = [row["event"], labels[row["classification"]], "; ".join(row["direct_paths"] + row["internal_paths"]),
                 ", ".join(name + ": " + str(delta) for name, delta in influence.items()) or "无配置"]
        lines.append("| " + " | ".join(map(cell, cells)) + " |")
    lines += ["", "完整规则、条件、配置的优先级/冷却与代码入口见 capabilities.json；人格修正、元数据倍增和运行门控由原模块执行。", ""]
    return "\n".join(lines)


def backlog(value):
    decisions = value.get("capability_decisions", {}).get("behaviors", {})
    entries = [
        {"capability_id": row["capability_id"], "missing_templates": row["missing_templates"],
         "owner_roles": ["BehaviorTree", "Action"], "decision": "UNDECIDED",
         "options": ["implement_with_acceptance", "explicitly_not_in_release", "retire_after_review"]}
        for row in value["routes"] + value["supplemental_routes"] if row["missing_templates"]]
    for entry in entries:
        known = {n: decisions[n] for n in entry["missing_templates"] if n in decisions}
        entry["behavior_decisions"] = known
        if len(known) == len(entry["missing_templates"]) and all(
                d["decision"] == "deferred_integration" for d in known.values()):
            entry["decision"] = "DEFERRED_INTEGRATION"
            entry["owner_roles"] = sorted({r for d in known.values() for r in d["owner_roles"]})
            entry.pop("options")
    status = ("NO_MISSING_TEMPLATES" if not entries else "PRODUCT_DECISIONS_PENDING"
              if any(e["decision"] == "UNDECIDED" for e in entries) else "BLOCKED_DEPENDENCIES")
    return {"schema_version": 1, "status": status, "entries": entries}
