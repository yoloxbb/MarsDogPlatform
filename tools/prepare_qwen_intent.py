"""Verify/extract the user-supplied Qwen model, excluding Git metadata and hooks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import zipfile

from runtime_environment import ROOT
from prepare_cpu_models import verify, materialize, checked_zip, safe_path, sha256

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "out/models/qwen2.5-0.5b-instruct")
    args = parser.parse_args(argv)
    lock_path = ROOT / "config/models/qwen2.5-0.5b-intent.lock.json"
    lock = json.loads(lock_path.read_text())
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = {"status": "FAIL", "model_acceptance": False}
    try:
        verify(args.archive, lock["archive"])
        with zipfile.ZipFile(args.archive) as archive:
            checked_zip(archive)
            for entry in lock["files"]:
                materialize(safe_path(root, entry["path"]), entry,
                            lambda e=entry: archive.open(e["member"]))
        provider = {"enabled": True, "type": "qwen_cpu",
                    "config": {"model": str(root), "num_threads": 2, "max_context_len": 4096,
                               "max_new_tokens": 32, "max_input_chars": 256}}
        (root / "intent-provider.json").write_text(json.dumps(provider, indent=2) + "\n")
        manifest = {"schema_version": 1, "model_directory": str(root),
                    "model_lock": str(lock_path),
                    "cases": str(ROOT / "modules/voice/tests/data/cpu_intent_cases.json"),
                    "provider": provider}
        (root / "intent-replay.json").write_text(json.dumps(manifest, indent=2) + "\n")
        report.update(status="READY", model_directory=str(root), lock_sha256=sha256(lock_path),
                      files=len(lock["files"]), git_metadata_extracted=False,
                      replay_manifest=str(root / "intent-replay.json"))
    except Exception as exc:
        report["error"] = str(exc)
    directory = root / "receipts"
    directory.mkdir(exist_ok=True)
    path = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({**report, "receipt": str(path)}))
    return 0 if report["status"] == "READY" else 1

if __name__ == "__main__":
    raise SystemExit(main())
