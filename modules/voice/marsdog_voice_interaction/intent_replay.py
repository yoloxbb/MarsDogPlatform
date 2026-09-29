"""Direct CPU model classification and existing event gates; no rule/catalog fallback."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

def replay(request):
    from marsdog_voice_interaction.providers.intent_factory import create_intent_provider
    from marsdog_voice_interaction.messages.intent_event_router import route_classification_events
    from marsdog_voice_interaction.adapters.llm import cpu_intent_prompt
    prompt_hash = hashlib.sha256(Path(cpu_intent_prompt.__file__).read_bytes()).hexdigest()
    provider = create_intent_provider(request["provider"])
    if provider is None or request["provider"].get("type") != "qwen_cpu":
        raise ValueError("Only explicit qwen_cpu is accepted in this replay")
    records = []
    try:
        provider.start()
        if not provider.is_available():
            raise RuntimeError(provider.last_error or "CPU model unavailable")
        for case in request["cases"]:
            started = time.perf_counter()
            result = provider.parse_intent(case["text"])
            events = route_classification_events(
                result["social"], result["intent"], result["control"],
                asr_text=case["text"], source=result["intent_source"]) if result else []
            errors = []
            if not result or result["raw_nlu_tag"] != case["expected_tag"]:
                errors.append("classification_mismatch")
            if case["must_not_execute"] and any(e["is_executable"] for e in events):
                errors.append("unexpected_executable_event")
            records.append({"id": case["id"], "text": case["text"],
                "expected_tag": case["expected_tag"], "raw_output": provider.last_output,
                "provider_error": provider.last_error, "input_rejected": provider.input_rejected,
                "classification": result,
                "events": events, "status": "FAIL" if errors else "PASS", "errors": errors,
                "elapsed_ms": round((time.perf_counter()-started)*1000, 3)})
            print(json.dumps({"id": case["id"], "status": records[-1]["status"],
                              "tag": result["raw_nlu_tag"] if result else None}, ensure_ascii=False), flush=True)
    finally:
        provider.stop()
    import torch
    return {"status": "PASS" if all(x["status"] == "PASS" for x in records) else "FAIL",
            "device": "cpu", "real_model_inference": True, "cases": records,
            "passed": sum(x["status"] == "PASS" for x in records),
            "input_rejections": sum(x["input_rejected"] for x in records),
            "unexpected_execution_cases": sum("unexpected_executable_event" in x["errors"] for x in records),
            "prompt_version": cpu_intent_prompt.PROMPT_VERSION,
            "prompt_module_sha256": prompt_hash,
            "versions": {k: importlib.metadata.version(k) for k in ("torch", "transformers", "tokenizers", "safetensors")},
            "torch_cuda_build": torch.version.cuda,
            "scope": "Direct prompted CPU classification + existing event payload gates; no catalog/rule fallback, ROS, audio or hardware"}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = replay(json.loads(args.request.read_text()))
    except Exception as exc:
        report = {"status": "FAIL", "device": "cpu", "real_model_inference": False, "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
