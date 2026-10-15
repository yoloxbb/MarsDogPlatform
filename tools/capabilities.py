"""Generate the Voice/BT/Action capability view; never load foreign business code."""
import argparse
import json
from pathlib import Path
import subprocess
from capability_snapshot import (describe_route, supplement, evidence_references, release_manifest,
                                 event_markdown, backlog, cell)
from runtime_environment import ROOT, clean_environment
from check_identifiers import CATALOG, EXCEPTIONS, check_freshness, validate


def combine(catalog, action):
    rows = [describe_route(route, action) for route in catalog["routes"]]
    return {"schema_version": 1, "catalog_source_sha256": catalog["source_sha256"],
            "voice_commands": catalog["voice_commands"], "routes": rows,
            "capability_decisions": catalog.get("capability_decisions", {}),
            "social_reactions": catalog["social_reactions"], "action": action,
            "supplemental_routes": supplement(catalog, action),
            "event_index": catalog.get("event_index", []),
            "route_policies": catalog.get("route_policies", {}),
            "category_policies": catalog.get("category_policies", {}),
            "tactile_policy": catalog.get("tactile_policy", {}),
            "emotion_deduplication_window_sec": catalog.get("emotion_deduplication_window_sec"),
            "coverage": catalog.get("coverage", {}),
            "hardware_acceptance": "unknown",
            "limits": ["Catalog recognition is not ASR accuracy.",
                       "Declared routes omit code-only/session paths.",
                       "An existing template or passing policy does not prove live executability."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=ROOT / "modules/action/config")
    parser.add_argument("--chassis", choices=("lite3", "go2"), default="lite3")
    parser.add_argument("--runtime-json", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "out/capabilities")
    parser.add_argument("--validation-report", type=Path, action="append", default=[],
                        help="Attach a JSON result as a reference, never as per-capability acceptance")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    def write_json(name, value):
        target = args.output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    for name in ("capabilities.json", "release_manifest.json", "result.json", "capability_backlog.json"):
        write_json(name, {"status": "RUNNING"})
    for name in ("README.md", "EVENT_ROUTES.md"):
        (args.output / name).write_text("# 正在生成；当前目录不代表已通过的报告\n", encoding="utf-8")
    try:
        catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
        check_freshness(catalog, ROOT)
        gate = validate(catalog, json.loads((ROOT / EXCEPTIONS).read_text(encoding="utf-8")))
        if gate["status"] == "FAIL" or catalog.get("event_routing_version") != 1:
            raise ValueError("catalog validation failed: " + str(gate["errors"]))
        references = evidence_references(args.validation_report, ROOT)
        source = ROOT / "modules/action"
        cmd = [str(source / ".venv/bin/python"), "-B", "-m", "marsdog_action_executor.capability_report",
               "--config-dir", str(args.config_dir.resolve()), "--chassis", args.chassis]
        if args.runtime_json:
            cmd += ["--runtime-json", str(args.runtime_json.resolve())]
        run = subprocess.run(cmd, cwd=source, env=clean_environment(), capture_output=True, text=True, timeout=60)
        if run.returncode:
            raise RuntimeError(run.stderr)
        action = json.loads(run.stdout)
        expected = source / "marsdog_action_executor/capability_report.py"
        if Path(action["module_file"]).resolve() != expected.resolve():
            raise ValueError("Action reporter did not load from the requested checkout")
        value = combine(catalog, action)
        write_json("capabilities.json", value)
        write_json("capability_backlog.json", backlog(value))
        (args.output / "EVENT_ROUTES.md").write_text(event_markdown(value), encoding="utf-8")
        write_readme(args.output, value)
        manifest = release_manifest(value, (args.output / "capabilities.json").read_bytes(), ROOT, references)
        write_json("release_manifest.json", manifest)
        report = {"status": "PASS_WITH_KNOWN_GAPS" if manifest["counts"]["missing_template_routes"] else "PASS",
                  "counts": manifest["counts"], "scope": "Offline configuration snapshot; no runtime or hardware acceptance"}
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        report = {"status": "FAIL", "error": str(error)}
        for name in ("capabilities.json", "release_manifest.json", "capability_backlog.json"):
            write_json(name, report)
        for name in ("README.md", "EVENT_ROUTES.md"):
            (args.output / name).write_text("# 报告生成失败\n\n" + str(error) + "\n", encoding="utf-8")
    write_json("result.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return int(report["status"] == "FAIL")


def write_readme(output, value):
    lines = ["# 当前配置能力清单", "", "由原配置生成；运行时授权、目标、姿态及设备状态仍需检查。硬件验收为 unknown。", "",
             "| 事件 | 上下文 | 下游行为 | 配置状态 |", "| --- | --- | --- | --- |"]
    for row in value["routes"] + value["supplemental_routes"]:
        lines.append("| " + " | ".join(map(cell, [row.get("event", ", ".join(row.get("events", []))),
                     row.get("context", row.get("id", "")), ", ".join(row["executor_behaviors"]),
                     row["configuration_status"]])) + " |")
    lines += ["", "事件分流见 EVENT_ROUTES.md；缺模板决策队列见 capability_backlog.json。",
              "阶段、Unit、策略和独立验收状态见 capabilities.json；配置/锁文件哈希与验证引用见 release_manifest.json。",
              "验证报告引用不自动提升单项能力的验收状态。代码路径索引并非穷举，当前仅明确登记唤醒授权后的靠近。", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
