"""Run bounded CPU intent replay in Voice's own optional dependency environment."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess

from runtime_environment import ROOT, clean_environment
from prepare_cpu_models import sha256, verify, safe_path

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "out/intent-cpu/replay")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be 1..3600")
    directory = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    report = {"status": "FAIL", "model_acceptance": False, "run_directory": str(directory)}
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("Intent replay interrupted")
    old = signal.signal(signal.SIGTERM, interrupted)
    try:
        manifest = json.loads(args.manifest.read_text())
        if manifest.get("schema_version") != 1:
            raise ValueError("Expected manifest schema_version 1")
        def resolve(raw):
            path = Path(raw)
            return (args.manifest.parent / path).resolve() if not path.is_absolute() else path.resolve()
        model = resolve(manifest["model_directory"])
        lock_path = resolve(manifest["model_lock"])
        cases_path = resolve(manifest["cases"])
        lock = json.loads(lock_path.read_text())
        assets = [safe_path(model, x["path"]) for x in lock["files"]]
        for path, entry in zip(assets, lock["files"]):
            verify(path, entry)
        provider = manifest["provider"]
        if provider.get("type") != "qwen_cpu" or not provider.get("enabled"):
            raise ValueError("Explicit qwen_cpu provider required")
        if Path(provider["config"]["model"]).resolve() != model:
            raise ValueError("Provider model must equal verified model directory")
        cases = json.loads(cases_path.read_text())["cases"]
        ids = [x["id"] for x in cases]
        if not cases or len(cases) > 256 or len(set(ids)) != len(ids):
            raise ValueError("Need 1..256 unique annotated cases")
        for case in cases:
            if not isinstance(case["text"], str) or not case["text"].strip() or not isinstance(case["expected_tag"], str):
                raise ValueError("Invalid text/expected tag")
            if type(case["must_not_execute"]) is not bool:
                raise ValueError("Execution annotation must be explicit")
        evidence = {str(path): sha256(path) for path in [*assets, lock_path, cases_path, args.manifest]}
        source_files = sorted((ROOT / "modules/voice/marsdog_voice_interaction").rglob("*.py"))
        source_files.extend([ROOT / "modules/voice/pyproject.toml", ROOT / "modules/voice/uv.lock"])
        source_evidence = {str(path.relative_to(ROOT)): sha256(path) for path in source_files}
        report.update(input_sha256=evidence, source_sha256=source_evidence, cases=len(cases))
        request = directory / "request.json"
        request.write_text(json.dumps({"provider": provider, "cases": cases}, ensure_ascii=False, indent=2) + "\n")
        result_path = directory / "voice.json"
        env = clean_environment()
        env.update(PYTHONPATH=str(ROOT / "modules/voice"), PYTHONDONTWRITEBYTECODE="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="",
                   TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2")
        cmd = [str(ROOT / "modules/voice/.venv/bin/python"), "-B", "-m",
               "marsdog_voice_interaction.intent_replay", "--request", str(request), "--output", str(result_path)]
        with (directory / "voice.log").open("w") as log:
            proc = subprocess.Popen(cmd, env=env, cwd=directory, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=args.timeout)
            except BaseException:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                raise
        if not result_path.is_file():
            raise RuntimeError("Intent subprocess produced no report; exit " + str(code))
        data = json.loads(result_path.read_text())
        report.update(module=data, inference_executed=data.get("real_model_inference", False))
        if any(sha256(Path(path)) != value for path, value in evidence.items()):
            raise RuntimeError("Input changed during inference")
        if any(sha256(ROOT / path) != value for path, value in source_evidence.items()):
            raise RuntimeError("Source or dependency lock changed during inference")
        accepted = (code == 0 and data.get("status") == "PASS" and data.get("device") == "cpu"
                    and data.get("real_model_inference") and data.get("torch_cuda_build") is None
                    and [x["id"] for x in data.get("cases", [])] == ids
                    and all(x["status"] == "PASS" for x in data["cases"]))
        report.update(status="PASS" if accepted else "FAIL", model_acceptance=bool(accepted))
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="FAIL", model_acceptance=False, error=str(exc) or type(exc).__name__)
    finally:
        signal.signal(signal.SIGTERM, old)
        (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "model_acceptance": report["model_acceptance"],
                      "report": str(directory / "result.json")}))
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
