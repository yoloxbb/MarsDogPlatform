"""Build and test a clean Emotion wheel away from its source tree; no hardware."""
from __future__ import annotations

import argparse
from component_inventory import check_installed_components
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCRIPTS = {
    "time_controller_node", "midnight_test_node", "internal_need_node",
    "emotion_engine_node", "personality_node", "one1000_tactile_node",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--python", default="/usr/bin/python3.10")
    args = parser.parse_args()
    source = ROOT / "modules/emotion"
    output = ROOT / "out/emotion-install"
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text('{"status":"RUNNING"}\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="check-", dir=output) as temporary:
        work = Path(temporary)
        log = output / "commands.log"
        def run(command):
            process = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                     text=True, timeout=180)
            with log.open("a") as stream:
                stream.write(json.dumps(command) + "\n" + process.stdout + process.stderr)
            if process.returncode:
                raise RuntimeError(f"Command failed ({process.returncode}); see {log}")
            return process.stdout
        log.write_text("")
        run([args.uv, "build", "--wheel", "--out-dir", str(work / "wheels"), str(source)])
        wheels = list((work / "wheels").glob("*.whl"))
        assert len(wheels) == 1
        run([args.uv, "venv", "--python", args.python, str(work / "venv")])
        python = work / "venv/bin/python"
        run([args.uv, "pip", "install", "--python", str(python), str(wheels[0])])
        probe = """
import hashlib, json, pathlib, sys, importlib.metadata
from marsdog_core.need_system import MarsdogNeedSystem
from marsdog_core import config_loader
system = MarsdogNeedSystem()
config_dir = config_loader._GetDefaultConfigDir()
print(json.dumps({
 'module_file': config_loader.__file__,
 'config_dir': str(config_dir),
 'config_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in config_dir.glob('*.yaml')},
 'scripts': {e.name:e.value for e in importlib.metadata.distribution('marsdog-need-emotion').entry_points if e.group=='console_scripts'},
 'demands': sorted(system.state.demands),
 'yaml_installed': __import__('importlib.util', fromlist=['find_spec']).find_spec('yaml') is not None,
 'rclpy_installed': __import__('importlib.util', fromlist=['find_spec']).find_spec('rclpy') is not None
}))
"""
        observation = json.loads(run([str(python), "-B", "-c", probe]))
        observation["components"] = check_installed_components(run, python, source)
        assert set(observation["scripts"]) == EXPECTED_SCRIPTS, observation
        assert Path(observation["module_file"]).is_relative_to(work / "venv"), observation
        expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (source / "configs").glob("*.yaml")}
        assert observation["config_hashes"] == expected, observation
        assert not observation["rclpy_installed"]
        assert not observation["yaml_installed"], "JSON fallback must work without optional PyYAML"
        result = {"status": "PASS", "scope": "clean wheel; no ROS/no PyYAML; original config bytes",
                  "observation": observation}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
