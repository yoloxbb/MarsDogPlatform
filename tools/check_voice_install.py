"""Verify the Voice Python wheel away from source; never start devices or ROS."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--python", default="/usr/bin/python3.10")
    parser.add_argument("--source", type=Path, default=ROOT / "modules/voice")
    parser.add_argument("--output", type=Path, default=ROOT / "out/voice-install")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    result_path.write_text('{"status":"RUNNING"}\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    log = output / "commands.log"
    log.write_text("")
    try:
        with tempfile.TemporaryDirectory(prefix="check-", dir=output) as temporary:
            work = Path(temporary)

            def run(command):
                process = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                         text=True, timeout=300)
                with log.open("a") as stream:
                    stream.write(json.dumps(command) + "\n" + process.stdout + process.stderr)
                if process.returncode:
                    raise RuntimeError(f"Command failed ({process.returncode}); see {log}")
                return process.stdout

            run([args.uv, "build", "--wheel", "--out-dir", str(work / "wheels"), str(source)])
            wheels = list((work / "wheels").glob("*.whl"))
            assert len(wheels) == 1
            wheel_hash = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
            # Replay the original lock directly: pip's offline resolver may lack
            # index metadata even when uv sync has cached every locked artifact.
            project = work / "runtime"
            project.mkdir()
            for name in ("pyproject.toml", "uv.lock"):
                shutil.copy2(source / name, project / name)
            run([args.uv, "sync", "--project", str(project), "--locked", "--no-dev",
                 "--no-install-project", "--python", args.python])
            python = project / ".venv/bin/python"
            run([args.uv, "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])])
            run([args.uv, "pip", "check", "--python", str(python)])
            probe = """
import hashlib, importlib.metadata, importlib.util, json, pathlib, sys
import marsdog_voice_interaction
from marsdog_voice_interaction.utils.config_loader import load_config
from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
from marsdog_voice_interaction.api.speaker_api import SpeakerApiServer
package=pathlib.Path(marsdog_voice_interaction.__file__).parent
share=pathlib.Path(sys.prefix)/'share/marsdog_voice_interaction'
config=load_config(share/'config/voice.yaml')
catalog=CommandLexicon(config['command_lexicon']['catalog'])
match=catalog.match('回家')
assert match is not None and match.event_type=='EVT_VOICE_COMMAND_GO_HOME'
assert config['topics']['audio_event']=='/perception/audio_event'
assert config['storage']['root']==str(share/'data')
api=SpeakerApiServer({'enabled':False}, lambda name,data: {'ok':True})
schema=api.create_app().openapi()
assets={str(p.relative_to(share)):hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ['config','launch'] for p in (share/folder).rglob('*') if p.is_file()}
assets['package.xml']=hashlib.sha256((share/'package.xml').read_bytes()).hexdigest()
static={str(p.relative_to(package/'api/static')):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (package/'api/static').rglob('*') if p.is_file()}
scripts={e.name:e.value for e in importlib.metadata.distribution('marsdog-voice-interaction').entry_points
         if e.group=='console_scripts'}
print(json.dumps({
 'module_file':str(package), 'asset_hashes':assets, 'static_hashes':static,
 'scripts':scripts, 'catalog_command_count':catalog.command_count,
 'catalog_phrase_count':catalog.phrase_count, 'api_paths':sorted(schema['paths']),
 'api_schema_sha256':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
 'topics':config['topics'], 'rclpy_installed':importlib.util.find_spec('rclpy') is not None,
 'native_library_in_wheel':(share/'lib/librkllmrt.so').exists(),
 'versions':{name:importlib.metadata.version(name) for name in
             ['numpy','scipy','sherpa-onnx','sherpa-onnx-core','fastapi','pydantic']}
}))
"""
            observation = json.loads(run([str(python), "-B", "-c", probe]))
            if (source / "marsdog_voice_interaction/replay.py").is_file():
                replay_code = (
                    "import hashlib,json,pathlib;import marsdog_voice_interaction.replay as replay;"
                    "p=pathlib.Path(replay.__file__);"
                    "print(json.dumps({'module_file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))")
                replay_entry = json.loads(run([str(python), "-B", "-c", replay_code]))
                assert Path(replay_entry["module_file"]).is_relative_to(project / ".venv")
                assert replay_entry["sha256"] == hashlib.sha256((source / "marsdog_voice_interaction/replay.py").read_bytes()).hexdigest()
                run([str(python), "-B", "-m", "marsdog_voice_interaction.replay", "--help"])
                observation["replay_entrypoint"] = replay_entry
            assert Path(observation["module_file"]).is_relative_to(project / ".venv")
            assert not observation["rclpy_installed"]
            assert observation["scripts"] == {
                "marsdog-voice-interaction": "marsdog_voice_interaction.main:main",
            }
            expected = {
                str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ("config", "launch") for p in (source / folder).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            }
            expected["package.xml"] = hashlib.sha256((source / "package.xml").read_bytes()).hexdigest()
            assert observation["asset_hashes"] == expected, "Installed config/launch differs"
            static = source / "marsdog_voice_interaction/api/static"
            assert observation["static_hashes"] == {
                str(p.relative_to(static)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in static.rglob("*") if p.is_file()
            }
            assert observation["catalog_command_count"] == 82
            assert observation["catalog_phrase_count"] == 156
            assert "/health" in observation["api_paths"]
            result = {
                "status": "PASS", "source": str(source), "wheel_sha256": wheel_hash,
                "lock_sha256": hashlib.sha256((source / "uv.lock").read_bytes()).hexdigest(),
                "scope": "Locked Python wheel; exact config/static bytes; HTTP schema only, no sockets; no ROS/node/hardware/models",
                "limits": ["ROS service generated separately by colcon",
                           "ARM64 RKLLM library is retained by ROS install, not this pure Python wheel",
                           "Production entry point metadata checked; main intentionally not invoked"],
                "observation": observation,
            }
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        result_path.write_text(json.dumps({"status": "FAIL", "error": str(error),
                                           "log": str(log)}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
