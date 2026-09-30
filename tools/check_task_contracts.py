"""Keep VoiceTask and VisionTask envelopes compatible without merging ROS identities."""
import json
import sys
from contract_harness import ROOT, check_main, run_stage

FIXTURES = ROOT / "interfaces/application/perception-task"
WORKER = ROOT / "integration/contracts/task_stage.py"


def observe(output):
    cases = json.loads((FIXTURES / "cases.json").read_text())["cases"]
    responses = {stage: run_stage(stage, cases, output, WORKER, ros=True)
                 for stage in ("voice", "vision")}
    return ({stage: value["observed"] for stage, value in responses.items()},
            {stage: value["provenance"] for stage, value in responses.items()})


if __name__ == "__main__":
    sys.exit(check_main(FIXTURES, observe, ROOT / "out/task-contracts", count_stage="voice"))
