"""Build/install Action away from source; verify exact configs/media and callable entries."""
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
    source = ROOT / "modules/action"
    output = ROOT / "out/action-install"
    output.mkdir(parents=True, exist_ok=True)
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
        log.write_text("")

        def run(command):
            process = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                     text=True, timeout=180)
            with log.open("a") as stream:
                stream.write(json.dumps(command) + "\n" + process.stdout + process.stderr)
            if process.returncode:
                raise RuntimeError(f"Command failed ({process.returncode}); see {log}")
            return process.stdout

        requirements = work / "requirements.txt"
        requirements.write_text(run([
            args.uv, "export", "--project", str(source), "--locked", "--no-dev",
            "--no-emit-project", "--format", "requirements.txt",
        ]))
        run([args.uv, "build", "--wheel", "--out-dir", str(work / "wheels"), str(source)])
        wheels = list((work / "wheels").glob("*.whl"))
        assert len(wheels) == 1
        run([args.uv, "venv", "--python", args.python, str(work / "venv")])
        python = work / "venv/bin/python"
        run([args.uv, "pip", "install", "--python", str(python), "-r", str(requirements), str(wheels[0])])
        probe = """
import hashlib,json,importlib.metadata,importlib.util,pathlib
from marsdog_action_executor import config_loader,emotion_display
loader=config_loader.ConfigLoader()
loader.load_all()
configs=loader.config_dir
scripts={e.name:e for e in importlib.metadata.distribution('marsdog-action-executor').entry_points if e.group=='console_scripts'}
for entry in scripts.values():
    assert callable(entry.load()), entry
for category in emotion_display.EMOTION_MAP:
    assert pathlib.Path(emotion_display._image_path(category)).is_file(), category
print(json.dumps({
 'module_file':config_loader.__file__, 'config_dir':str(configs),
 'asset_hashes':{str(p.relative_to(configs)):hashlib.sha256(p.read_bytes()).hexdigest() for p in configs.rglob('*') if p.is_file()},
 'scripts':{k:v.value for k,v in scripts.items()}, 'behavior_count':len(loader.get_behavior_names()),
 'rclpy_installed':importlib.util.find_spec('rclpy') is not None,
 'numpy_version':importlib.metadata.version('numpy')
}))
"""
        observation = json.loads(run([str(python), "-B", "-c", probe]))
        assert set(observation["scripts"]) == {"marsdog-action-demo", "action_executor_node", "emotion_display"}
        assert Path(observation["module_file"]).is_relative_to(work / "venv")
        expected = {str(p.relative_to(source / "config")): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (source / "config").rglob("*") if p.is_file()}
        assert observation["asset_hashes"] == expected
        assert observation["behavior_count"] > 0 and not observation["rclpy_installed"]
        result = {"status": "PASS", "scope": "clean locked Action wheel; no ROS/hardware; original config/media bytes",
                  "observation": observation}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
