"""Build unchanged snapshot wheels and probe fresh installs outside their source cwd."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from baseline_lib import ROOT, clean_environment, verify_sources
from run_module_checks import command

PROBES = {
    "emotion": """
import json, sys, pathlib, importlib.metadata
from marsdog_core.need_system import MarsdogNeedSystem
from marsdog_core import config_loader
report = {'module_file': config_loader.__file__, 'sys_prefix': sys.prefix,
 'console_scripts': [e.name for e in importlib.metadata.distribution('marsdog-need-emotion').entry_points]}
try:
 system = MarsdogNeedSystem()
 report['default_configuration'] = {'status': 'PASS', 'demands': sorted(system.state.demands)}
except Exception as e:
 report['default_configuration'] = {'status': 'FAIL', 'error': repr(e)}
config = pathlib.Path(sys.prefix) / 'share/marsdog_need_emotion/configs'
try:
 system = MarsdogNeedSystem(configDir=config)
 report['explicit_installed_configuration'] = {'status': 'PASS', 'demands': sorted(system.state.demands)}
except Exception as e:
 report['explicit_installed_configuration'] = {'status': 'FAIL', 'error': repr(e)}
print(json.dumps(report))
""",
    "behavior": """
import json, sys, importlib.metadata
from marsdog_behavior.result_event_mapper import ResultEventMapper
from marsdog_behavior.runtime import BehaviorRuntime
from marsdog_behavior.config_paths import get_config_file
import marsdog_behavior
report = {'module_file': marsdog_behavior.__file__, 'sys_prefix': sys.prefix,
 'console_scripts': [e.name for e in importlib.metadata.distribution('marsdog-behavior').entry_points]}
try:
 path = get_config_file('behaviors.yaml')
 report['default_configuration'] = {'status': 'PASS' if path.exists() else 'FAIL', 'path': str(path)}
except Exception as e:
 report['default_configuration'] = {'status': 'FAIL', 'error': repr(e)}
print(json.dumps(report))
""",
    "action": """
import json, sys, pathlib, importlib.metadata
from marsdog_action_executor.config_loader import ConfigLoader
from marsdog_action_executor import ros_node
report = {'module_file': ros_node.__file__, 'sys_prefix': sys.prefix,
 'console_scripts': [e.name for e in importlib.metadata.distribution('marsdog-action-executor').entry_points]}
config = pathlib.Path(sys.prefix) / 'share/marsdog_action_executor/config'
try:
 loader = ConfigLoader(str(config)); loader.load_all()
 report['installed_configuration'] = {'status': 'PASS', 'path': str(config)}
except Exception as e:
 report['installed_configuration'] = {'status': 'FAIL', 'error': repr(e)}
print(json.dumps(report))
""",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run-id")
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Baseline changed")
    report = ROOT / "reports" / args.run_id
    work = ROOT / "work" / args.run_id
    neutral = work / "neutral-cwd"
    neutral.mkdir(exist_ok=True)
    uv = str(ROOT / ".tools/uv")
    results = {}
    for module in PROBES:
        source = work / "sources" / module
        wheels = work / "wheels" / module
        wheels.mkdir(parents=True, exist_ok=True)
        records = [command([
            uv, "build", "--wheel", "--out-dir", str(wheels), str(source),
        ], neutral, report / f"{module}-wheel-build.log")]
        if records[-1]["exit_code"]:
            results[module] = {"status": "FAIL", "stage": "wheel-build", "checks": records}
            continue
        wheel = list(wheels.glob("*.whl"))
        if len(wheel) != 1:
            raise SystemExit(f"Expected one wheel for {module}: {wheel}")
        envdir = work / "installed" / module
        python = envdir / "bin/python"
        records.append(command([uv, "venv", "--python", "/usr/bin/python3.10", str(envdir)],
                               neutral, report / f"{module}-installed-venv.log"))
        records.append(command([
            uv, "pip", "install", "--python", str(python), "--requirements",
            str(report / f"{module}-installed.txt"), str(wheel[0]),
        ], neutral, report / f"{module}-wheel-install.log"))
        if records[-1]["exit_code"]:
            results[module] = {"status": "FAIL", "stage": "wheel-install", "checks": records}
            continue
        probe = command([str(python), "-B", "-c", PROBES[module]],
                        neutral, report / f"{module}-installed-probe.json")
        records.append(probe)
        if probe["exit_code"] == 0:
            observation = json.loads(Path(probe["log"]).read_text())
            assert Path(observation["module_file"]).is_relative_to(envdir)
            outcomes = [value["status"] for value in observation.values()
                        if isinstance(value, dict) and "status" in value]
            status = "PASS" if all(s == "PASS" for s in outcomes) else "FAIL"
        else:
            observation, status = {}, "FAIL"
        results[module] = {"status": status, "scope": "Python wheel; not ROS install",
                           "observation": observation, "checks": records}
        print(module, status, flush=True)
    results["original_sources"] = verify_sources()
    (report / "packaging.json").write_text(json.dumps(results, indent=2) + "\n")
    raise SystemExit(0 if all(r["status"] == "PASS" for r in results.values()) else 1)


if __name__ == "__main__":
    main()
