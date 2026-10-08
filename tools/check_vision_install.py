"""Verify a locked Vision wheel with CPU math and installed resources, no cameras/models."""
import argparse
from component_inventory import check_installed_components
from observability_install import copy_source
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=ROOT / "modules/vision")
    p.add_argument("--output", type=Path, default=ROOT / "out/vision-install")
    p.add_argument("--uv", default="uv")
    p.add_argument("--allow-legacy-gaps", action="store_true")
    a = p.parse_args()
    source, out = a.source.resolve(), a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = out / "result.json"
    report.write_text('{"status":"RUNNING"}\n')
    log = out / "commands.log"
    log.write_text("")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never",
               CUDA_VISIBLE_DEVICES="", QT_QPA_PLATFORM="offscreen")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for k in list(env):
        if k.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "MARSDOG_VISION_")):
            env.pop(k)
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(k, None)
    try:
        with tempfile.TemporaryDirectory(prefix="check-", dir=out) as temp:
            work = Path(temp)
            env["YOLO_CONFIG_DIR"] = str(work / "yolo")
            def run(cmd):
                r = subprocess.run(cmd, cwd=work, env=env, text=True, capture_output=True, timeout=300)
                with log.open("a") as f:
                    f.write(json.dumps(cmd) + "\n" + r.stdout + r.stderr)
                if r.returncode:
                    raise RuntimeError(f"Exit {r.returncode}: {cmd}; see {log}")
                return r.stdout
            run([a.uv, "build", "--wheel", "--out-dir", str(work / "wheels"), str(source)])
            copy_source(work)
            project = work / "modules" / source.name
            project.mkdir(parents=True)
            for n in ("pyproject.toml", "uv.lock"):
                shutil.copy2(source / n, project / n)
            run([a.uv, "sync", "--project", str(project), "--locked", "--no-dev", "--extra", "models",
                 "--no-install-project", "--python", "/usr/bin/python3.10"])
            python = project / ".venv/bin/python"
            wheel = next((work / "wheels").glob("*.whl"))
            run([a.uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)])
            run([a.uv, "pip", "check", "--python", str(python)])
            probe = """
import pathlib, sys, json, hashlib, os, importlib.metadata
import numpy as np
import cv2, torch
import marsdog_vision_interaction as package
from marsdog_vision_interaction.utils.config_loader import load_config
root=pathlib.Path(package.__file__).parent
share=pathlib.Path(sys.prefix)/'share/marsdog_vision_interaction'
os.environ['MARSDOG_VISION_PROJECT_DIR']=str(share)
os.environ['MARSDOG_VISION_DATA_DIR']=str(share/'data')
os.environ.pop('MARSDOG_MODEL_DIR', None)
os.environ.pop('MARSDOG_VISION_MODEL_DIR', None)
config=load_config(share/'config/vision.yaml')
assert config['providers']['vision']['config']['face_detect_model']==str(pathlib.Path(MODEL_ROOT_LITERAL)/'vision/face_detection_yunet_2023mar_fp16.rknn')
os.environ['MARSDOG_MODEL_DIR']=str(share/'external-models')
config=load_config(share/'config/vision.yaml')
assert config['providers']['vision']['config']['face_detect_model']==str(share/'external-models/vision/face_detection_yunet_2023mar_fp16.rknn')
os.environ['MARSDOG_VISION_MODEL_DIR']=str(share/'models')
config=load_config(share/'config/vision.yaml')
assert config['providers']['vision']['config']['face_detect_model']==str(share/'models/face_detection_yunet_2023mar_fp16.rknn')
assert torch.ones((2,2), device='cpu').matmul(torch.ones((2,2),device='cpu')).sum().item()==8
assert cv2.resize(np.zeros((4,4,3),np.uint8),(2,2)).shape==(2,2,3)
assert hasattr(cv2,'FaceDetectorYN_create') and hasattr(cv2,'FaceRecognizerSF_create')
scripts={e.name:e.value for e in importlib.metadata.distribution('marsdog-vision-interaction').entry_points if e.group=='console_scripts'}
assets={str(p.relative_to(share)):hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ['config','launch'] for p in (share/folder).rglob('*') if p.is_file()}
for n in ['package.xml','fastdds_env.sh']:
 p=share/n
 if p.is_file(): assets[n]=hashlib.sha256(p.read_bytes()).hexdigest()
web={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'web').glob('*.html')}
print(json.dumps({'module_file':str(root),'scripts':scripts,'assets':assets,'web':web,
 'topics':config['topics'],'cpu_math':True,'cv2_version':cv2.__version__,
 'cv2_contrib_face_namespace':hasattr(cv2,'face'),
 'versions':{n:importlib.metadata.version(n) for n in ['numpy','opencv-python','opencv-contrib-python','torch','mediapipe','protobuf','pydantic']}}))
"""
            probe = probe.replace("MODEL_ROOT_LITERAL", repr(str(ROOT / "models")))
            observation = json.loads(run([str(python), "-B", "-c", probe]))
            observation["components"] = check_installed_components(run, python, source)
            if (source / "marsdog_vision_interaction/replay.py").is_file():
                replay_code = (
                    "import hashlib,json,pathlib;import marsdog_vision_interaction.replay as replay;"
                    "p=pathlib.Path(replay.__file__);"
                    "print(json.dumps({'module_file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))")
                replay_entry = json.loads(run([str(python), "-B", "-c", replay_code]))
                assert Path(replay_entry["module_file"]).is_relative_to(project / ".venv")
                assert replay_entry["sha256"] == hashlib.sha256((source / "marsdog_vision_interaction/replay.py").read_bytes()).hexdigest()
                run([str(python), "-B", "-m", "marsdog_vision_interaction.replay", "--help"])
                observation["replay_entrypoint"] = replay_entry
            assert Path(observation["module_file"]).is_relative_to(project / ".venv")
            expected = {str(f.relative_to(source)): hashlib.sha256(f.read_bytes()).hexdigest()
                        for folder in ("config", "launch") for f in (source / folder).rglob("*")
                        if f.is_file() and "__pycache__" not in f.parts}
            expected["package.xml"] = hashlib.sha256((source / "package.xml").read_bytes()).hexdigest()
            expected["fastdds_env.sh"] = hashlib.sha256((source / "scripts/fastdds_env.sh").read_bytes()).hexdigest()
            missing = sorted(set(expected) - set(observation["assets"]))
            if missing:
                assert a.allow_legacy_gaps and missing == ["config/fastdds.xml", "fastdds_env.sh"], missing
            assert all(observation["assets"].get(n) == h for n,h in expected.items() if n not in missing)
            assert set(observation["assets"]) <= set(expected)
            assert observation["web"] == {f.name:hashlib.sha256(f.read_bytes()).hexdigest()
                                         for f in (source / "marsdog_vision_interaction/web").glob("*.html")}
            assert set(observation["scripts"]) == {"marsdog-vision-interaction","marsdog-camera-driver","marsdog-vision-viewer"}
            result = {"status":"KNOWN_PACKAGING_GAP" if missing else "PASS","missing_resources":missing,
                      "source":str(source),"scope":"Original locked CPU runtime and wheel resources; no model/device inference",
                      "lock_sha256":hashlib.sha256((source/"uv.lock").read_bytes()).hexdigest(),"observation":observation}
            report.write_text(json.dumps(result,indent=2)+"\n")
            print(json.dumps({"status":result["status"],"missing_resources":missing,"report":str(report)}))
    except Exception as e:
        report.write_text(json.dumps({"status":"FAIL","error":str(e)},indent=2)+"\n")
        raise


if __name__ == "__main__":
    main()
