"""Materialize pinned CPU assets, then prepare the module-owned YOLOE model."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from runtime_environment import ROOT, clean_environment
from model_assets import CPU_BUNDLE, model_directory

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_path(root, name):
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe asset path: " + name)
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()) or target.resolve() == root.resolve():
        raise ValueError("Asset path escapes destination: " + name)
    return target

def verify(path, spec):
    if path.stat().st_size != spec["size"] or sha256(path) != spec["sha256"]:
        raise ValueError("Asset size/SHA256 mismatch: " + str(path))

def materialize(target, spec, source):
    """Never overwrite an existing mismatched file; publish only verified bytes."""
    if target.exists():
        verify(target, spec)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
            temporary = Path(out.name)
            h, size = hashlib.sha256(), 0
            with source() as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    if size > spec["size"]:
                        raise ValueError("Asset exceeds locked size")
                    out.write(block)
                    h.update(block)
        if size != spec["size"] or h.hexdigest() != spec["sha256"]:
            raise ValueError("Downloaded/extracted asset checksum mismatch")
        os.link(temporary, target)  # Atomic, refuses races/overwrites.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

def checked_zip(archive):
    seen = set()
    for info in archive.infolist():
        safe_path(Path("/asset-check"), info.filename)
        if info.filename in seen or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("Duplicate or linked ZIP entry: " + info.filename)
        seen.add(info.filename)

def unpack_tools(root, lock):
    target = root / "text-tools"
    target.mkdir(exist_ok=True)
    # These pinned wheels are used only on PYTHONPATH of the preparation process.
    for entry in lock["downloads"]:
        if not entry["path"].endswith(".whl"):
            continue
        with zipfile.ZipFile(root / "downloads" / entry["path"]) as archive:
            checked_zip(archive)
            for info in archive.infolist():
                if info.is_dir():
                    continue
                blob = archive.read(info)
                materialize(safe_path(target, info.filename),
                            {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()},
                            lambda b=blob: io.BytesIO(b))
    with tarfile.open(root / "downloads/clip-a13192f8.tar.gz") as archive:
        for info in archive.getmembers():
            relative = PurePosixPath(*PurePosixPath(info.name).parts[1:])
            if not relative.parts or not (relative.parts[0] == "clip" or relative.name in ("LICENSE", "README.md", "pyproject.toml")):
                continue
            if info.issym() or info.islnk():
                raise ValueError("Linked text-tool source")
            if info.isfile():
                blob = archive.extractfile(info).read()
                materialize(safe_path(target, str(relative)),
                            {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()},
                            lambda b=blob: io.BytesIO(b))

def run_owned(command, cwd, env):
    proc = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    try:
        if proc.wait(timeout=600):
            raise RuntimeError("YOLOE preparation failed")
    except BaseException:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        raise

def prepare(args):
    lock = json.loads(args.lock.read_text())
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    verify(args.archive, lock["archive"])
    with zipfile.ZipFile(args.archive) as archive:
        checked_zip(archive)
        for entry in lock["archive_files"]:
            info = archive.getinfo(entry["member"])
            materialize(safe_path(root / "archive", entry["member"]), entry,
                        lambda i=info: archive.open(i))
    for entry in lock["downloads"]:
        target = safe_path(root / "downloads", entry["path"])
        if not target.exists() and not args.download:
            raise FileNotFoundError("Missing " + str(target) + "; use --download to fetch pinned official sources")
        if not entry["url"].startswith("https://"):
            raise ValueError("Downloads require HTTPS")
        materialize(target, entry, lambda e=entry: urllib.request.urlopen(
            urllib.request.Request(e["url"], headers={"User-Agent": "MarsDog-model-preparation"}), timeout=60))
    unpack_tools(root, lock)
    with zipfile.ZipFile(root / "downloads/coco128.zip") as archive:
        checked_zip(archive)
        for item in lock["fixtures"]:
            for key in ("image", "annotation"):
                entry = item[key]
                materialize(safe_path(root / "fixtures", entry["member"]), entry,
                            lambda e=entry: archive.open(e["member"]))
    (root / "assets.lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    labels = root / "labels.json"
    labels.write_text(json.dumps(lock["vision_labels"], ensure_ascii=False, indent=2) + "\n")
    env = clean_environment()
    env.update(PYTHONPATH=str(root / "text-tools"), PYTHONDONTWRITEBYTECODE="1",
               CUDA_VISIBLE_DEVICES="", YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true",
               YOLO_CONFIG_DIR=str(root / "settings"), OMP_NUM_THREADS="2")
    run_owned([str(ROOT / "modules/vision/.venv/bin/python"), "-B",
               str(ROOT / "modules/vision/tools/prepare_cpu_yoloe.py"),
               "--assets", str(root), "--labels", str(labels)], root, env)
    def spec(path):
        return {"path": str(path), "sha256": sha256(path)}
    asr = root / "archive/models/asr/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    manifest = {"schema_version": 1,
        "description": "CPU same-scale YOLOE base with original 18 prompts, all COCO128 cat/dog labels fixed before inference; upstream SenseVoice ITN regression. Not production accuracy or RKNN numerical parity. Sources: config/models/cpu-assets.lock.json",
        "vision": {"model": spec(root / "derived/yoloe-26s-marsdog18.pt"),
                   "settings": {"image_size": 640, "confidence": 0.2, "iou": 0.2, "max_detections": 50},
                   "samples": [{"id": Path(x["image"]["member"]).stem,
                                "image": spec(root / "fixtures" / x["image"]["member"]),
                                "expected_labels": x["expected_labels"]} for x in lock["fixtures"]]},
        "voice": {"model_type": "sense_voice", "language": "zh", "num_threads": 2,
                  "model": spec(asr / "model.int8.onnx"), "tokens": spec(asr / "tokens.txt"),
                  "samples": [{"id": "upstream-zh-itn", "audio": spec(asr / "test_wavs/zh.wav"),
                               "expected_text": lock["voice_reference"]["text"]}]}}
    (root / "cpu-replay.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for module in ("vision", "voice"):
        single = {key: manifest[key] for key in ("schema_version", "description", module)}
        (root / (module + "-replay.json")).write_text(json.dumps(single, ensure_ascii=False, indent=2) + "\n")
    return {"status": "READY", "model_acceptance": False, "assets": str(root),
            "lock_sha256": sha256(args.lock), "manifest": str(root / "cpu-replay.json"),
            "scope": "Assets and CPU checkpoint prepared; run replay for inference acceptance",
            "unknown": ["Fine-tuned RKLLM original checkpoint", "RKNN/CPU numerical parity"]}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=model_directory() / CPU_BUNDLE)
    parser.add_argument("--lock", type=Path, default=ROOT / "config/models/cpu-assets.lock.json")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Model preparation interrupted")
    previous = signal.signal(signal.SIGTERM, interrupted)
    report = {"status": "FAIL", "model_acceptance": False}
    try:
        report = prepare(args)
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = str(exc) or type(exc).__name__
    finally:
        signal.signal(signal.SIGTERM, previous)
        directory = args.output / "receipts"
        directory.mkdir(parents=True, exist_ok=True)
        report_path = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**report, "receipt": str(report_path)}, ensure_ascii=False))
    return 0 if report["status"] == "READY" else 1

if __name__ == "__main__":
    raise SystemExit(main())
