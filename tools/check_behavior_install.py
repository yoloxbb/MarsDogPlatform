"""Verify the BT wheel's installed config, original demos and ROS entry point."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--python", default="/usr/bin/python3.10")
    args = parser.parse_args()
    source = ROOT / "modules/behavior"
    output = ROOT / "out/behavior-install"
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE", "MARSDOG_BEHAVIOR_CONFIG_DIR"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="check-", dir=output) as temporary:
        work = Path(temporary)
        log = output / "commands.log"
        log.write_text("")

        def run(command):
            process = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                     text=True, timeout=180)
            with log.open("a") as stream:
                stream.write(json.dumps(command) + "\n" + process.stdout + process.stderr)
            if process.returncode:
                raise RuntimeError(f"Command failed ({process.returncode}); see {log}")
            return process.stdout

        run([args.uv, "build", "--wheel", "--out-dir", str(work / "wheels"), str(source)])
        wheels = list((work / "wheels").glob("*.whl"))
        assert len(wheels) == 1
        run([args.uv, "venv", "--python", args.python, str(work / "venv")])
        python = work / "venv/bin/python"
        run([args.uv, "pip", "install", "--python", str(python), str(wheels[0])])
        probe = """
import hashlib,json,importlib.metadata,importlib.util
from marsdog_behavior import config_paths
from marsdog_behavior.intent_mapper import IntentMapper
from bionic_dog_bt.yaml_loader import YAMLLoader
configs=config_paths.get_config_dir()
specs=YAMLLoader(str(configs/'behaviors.yaml')).get_all_specs()
mapper=IntentMapper()
scripts={e.name:e for e in importlib.metadata.distribution('marsdog-behavior').entry_points if e.group=='console_scripts'}
for entry in scripts.values():
    assert callable(entry.load()), entry
print(json.dumps({
 'module_file':config_paths.__file__, 'config_dir':str(configs),
 'config_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in configs.glob('*.yaml')},
 'scripts':{k:v.value for k,v in scripts.items()}, 'behavior_count':len(specs),
 'rclpy_installed':importlib.util.find_spec('rclpy') is not None
}))
"""
        observation = json.loads(run([str(python), "-B", "-c", probe]))
        assert set(observation["scripts"]) == {"behavior-tree-demo", "marsdog-standalone", "behavior_tree_node"}
        assert Path(observation["module_file"]).is_relative_to(work / "venv")
        expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (source / "config").glob("*.yaml")}
        assert observation["config_hashes"] == expected
        assert observation["behavior_count"] > 0 and not observation["rclpy_installed"]
        result = {"status": "PASS", "scope": "clean BT wheel; no ROS; unmodified config bytes",
                  "observation": observation}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
