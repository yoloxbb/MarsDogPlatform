"""Generate the Voice/BT/Action capability view; never load foreign business code."""
import argparse
import json
from pathlib import Path
import subprocess
from runtime_environment import ROOT, clean_environment
from check_identifiers import CATALOG, check_freshness


def combine(catalog, action):
    rows = []
    for route in catalog["routes"]:
        names = route["executor_behaviors"]
        missing = [name for name in names if name not in action["behaviors"]]
        states = [action["behaviors"][name]["configuration_status"] for name in names if name not in missing]
        rows.append({**route, "missing_templates": missing,
                     "configuration_status": "missing_template" if missing else
                     ("blocked" if states and all(s == "blocked" for s in states) else "runtime_check_required")})
    return {"schema_version": 1, "catalog_source_sha256": catalog["source_sha256"],
            "voice_commands": catalog["voice_commands"], "routes": rows,
            "social_reactions": catalog["social_reactions"], "action": action,
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
    args = parser.parse_args(argv)
    catalog = json.loads((ROOT / CATALOG).read_text())
    check_freshness(catalog, ROOT)
    source = ROOT / "modules/action"
    cmd = [str(source / ".venv/bin/python"), "-B", "-m", "marsdog_action_executor.capability_report",
           "--config-dir", str(args.config_dir.resolve()), "--chassis", args.chassis]
    if args.runtime_json:
        cmd += ["--runtime-json", str(args.runtime_json.resolve())]
    run = subprocess.run(cmd, cwd=source, env=clean_environment(), capture_output=True, text=True, timeout=60)
    if run.returncode:
        raise RuntimeError(run.stderr)
    value = combine(catalog, json.loads(run.stdout))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "capabilities.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 当前配置能力清单", "", "由原配置生成；运行时授权、目标、姿态及设备状态仍需检查。硬件验收为 unknown。", "",
             "| 事件 | 上下文 | 下游行为 | 配置状态 |", "| --- | --- | --- | --- |"]
    for row in value["routes"]:
        lines.append("| " + " | ".join([row["event"], row["context"],
                     ", ".join(row["executor_behaviors"]), row["configuration_status"]]) + " |")
    lines += ["", "详细阶段、Unit、路由、策略门限与配置哈希见 capabilities.json。", ""]
    (args.output / "README.md").write_text("\n".join(lines))
    print(json.dumps({"report": str(args.output / "README.md"), "routes": len(value["routes"]),
                      "missing_template_routes": sum(bool(r["missing_templates"]) for r in value["routes"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
