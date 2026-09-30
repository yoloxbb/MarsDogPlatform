"""Verify Vision -> BT/Emotion/Action using the pre-refactor wire corpus."""
import json
from pathlib import Path
import sys
from contract_harness import ROOT, check_main, run_stage, write_json

FIXTURES = ROOT / "interfaces/application/visual-event-v1"
WORKER = ROOT / "integration/contracts/visual_stage.py"


def observe(output):
    fixtures = json.loads((FIXTURES / "cases.json").read_text())
    vision = run_stage("vision", fixtures["producers"], output, WORKER)
    scenarios = []
    for case in fixtures["scenarios"]:
        steps = []
        for step in case["steps"]:
            item = {"advance": step.get("advance", 0.0)}
            if "raw" in step:
                item["wire"] = step["raw"]
            elif "source" in step:
                payload = dict(vision["observed"][step["source"]])
                payload.update(step.get("patch", {}))
                for key in step.get("remove", []):
                    payload.pop(key, None)
                item["wire"] = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            steps.append(item)
        scenarios.append({"id": case["id"], "steps": steps})
    write_json(output / "wires.json", scenarios)
    responses = {"vision": vision}
    for stage in ("behavior", "emotion", "action"):
        responses[stage] = run_stage(stage, scenarios, output, WORKER)
    return ({stage: value["observed"] for stage, value in responses.items()},
            {stage: value["provenance"] for stage, value in responses.items()})


if __name__ == "__main__":
    sys.exit(check_main(FIXTURES, observe, ROOT / "out/visual-contracts"))
