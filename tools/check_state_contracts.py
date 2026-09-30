"""Freeze state/signal authority, levels and recovery between Emotion and BT."""
from copy import deepcopy
import json
import sys
from contract_harness import ROOT, check_main, run_stage, write_json

FIXTURES = ROOT / "interfaces/application/state-v2"
WORKER = ROOT / "integration/contracts/state_stage.py"


def observe(output):
    fixture = json.loads((FIXTURES / "cases.json").read_text())
    emotion = run_stage("emotion", fixture["producers"], output, WORKER)
    scenarios = []
    for spec in fixture["scenarios"]:
        batches = []
        for step in spec["steps"]:
            if "raw" in step:
                batch = [step["raw"]]
            else:
                batch = deepcopy(emotion["observed"][step["source"]][step.get("index", 0)])
                if "topics" in step:
                    batch = [m for m in batch if m["topic"] in step["topics"]]
                if "patch" in step:
                    for message in batch:
                        payload = json.loads(message["wire"])
                        payload.update(step["patch"])
                        message["wire"] = json.dumps(payload, ensure_ascii=False)
            batches.append(batch)
        scenarios.append({"id": spec["id"], "batches": batches})
    write_json(output / "wires.json", scenarios)
    behavior = run_stage("behavior", scenarios, output, WORKER)
    return ({"emotion": emotion["observed"], "behavior": behavior["observed"]},
            {"emotion": emotion["provenance"], "behavior": behavior["provenance"]})


if __name__ == "__main__":
    sys.exit(check_main(FIXTURES, observe, ROOT / "out/state-contracts"))
