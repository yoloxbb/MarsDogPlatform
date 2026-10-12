"""Verify Vision -> BT/Emotion/Action using the pre-refactor wire corpus."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from contract_harness import ROOT, check_main, run_stage, write_json

FIXTURES = ROOT / "interfaces/application/visual-event-v1"
WORKER = ROOT / "integration/contracts/visual_stage.py"


def observe(output):
    fixtures = json.loads((FIXTURES / "cases.json").read_text())
    vision = run_stage("vision", fixtures["producers"], output, WORKER)

    # Keep the frozen v1 corpus/baseline byte-for-byte stable. Validate the
    # newly optional Vision-owned field in a separate producer probe instead.
    probe_dir = output / "facial-expression-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    expression = {"expression": "happy", "confidence": 0.85}
    probe_payload = {
        "schema_version": 1,
        "vision_epoch": "expression-probe",
        "snapshot_id": "expression-probe:1",
        "sequence": 1,
        "header": {"stamp": 1000, "frame_id": "camera"},
        "faces": [{"track_id": 7, "facial_expression": expression}],
        "debug_faces": [{"track_id": 7, "facial_expression": expression}],
        "facial_expression_valid_for_sec": 0.5,
    }
    producer_probe = run_stage(
        "vision", {"facial_expression_probe": probe_payload}, probe_dir, WORKER
    )
    produced = producer_probe["observed"]["facial_expression_probe"]
    for key in ("faces", "debug_faces"):
        faces = produced.get(key)
        if not isinstance(faces, list) or len(faces) != 1 or not isinstance(faces[0], dict):
            raise RuntimeError(f"Vision producer did not preserve the {key} probe face")
        face = faces[0]
        if face.get("facial_expression") != expression:
            raise RuntimeError(f"Vision producer did not preserve canonical {key} expression")
        if set(face["facial_expression"]) != {"expression", "confidence"}:
            raise RuntimeError(f"Vision producer emitted noncanonical {key} expression fields")
    if produced.get("facial_expression_valid_for_sec") != 0.5:
        raise RuntimeError("Vision producer did not preserve facial-expression lifetime metadata")

    # Exercise the real Emotion consumer with identical event evidence, once
    # without and once with the optional face metadata. Its state/output must
    # remain identical; robot emotion continues to be driven by events[].
    control = deepcopy(vision["observed"]["owner"])
    for key in ("faces", "debug_faces"):
        control[key] = deepcopy(produced[key])
        for face in control[key]:
            face.pop("facial_expression", None)
    with_expression = deepcopy(control)
    for key in ("faces", "debug_faces"):
        with_expression[key] = deepcopy(produced[key])
    with_expression["facial_expression_valid_for_sec"] = 0.5
    emotion_scenarios = [
        {"id": "expression-control", "steps": [{"wire": json.dumps(control, ensure_ascii=False)}]},
        {"id": "expression-metadata", "steps": [{"wire": json.dumps(with_expression, ensure_ascii=False)}]},
    ]
    emotion_probe = run_stage(
        "emotion", emotion_scenarios, probe_dir, WORKER
    )
    if (emotion_probe["observed"]["expression-control"]
            != emotion_probe["observed"]["expression-metadata"]):
        raise RuntimeError("facial_expression metadata changed MarsDog Emotion consumer output")

    # Owner presence uses optional v1 metadata so the baseline's original
    # payload corpus and frozen consumer output stay untouched.
    owner_probe_dir = output / "owner-presence-probe"
    owner_probe_dir.mkdir(parents=True, exist_ok=True)
    owner_payload = {
        "schema_version": 1,
        "vision_epoch": "owner-probe-epoch",
        "snapshot_id": "owner-probe-epoch:1",
        "sequence": 1,
        "source_observation_id": "owner-probe-frame-1",
        "observation_status": "valid",
        "header": {"stamp": 1000, "frame_id": "camera"},
        "events": ["EVT_VISION_MASTER", "EVT_VISION_OWNER_PRESENT"],
        "event_instances": {
            "EVT_VISION_OWNER_PRESENT": {"event_id": "owner-probe-cycle-1"}
        },
        "human_candidates": [{
            "identity": "owner",
            "identity_state": "confirmed_known",
            "tracking_state": "tracking",
            "target_type": "human",
            "target_id": "owner-probe-epoch:human:7",
            "track_id": 7,
            "vision_epoch": "owner-probe-epoch",
            "last_seen_age_ms": 0.0,
        }],
    }
    owner_producer_probe = run_stage(
        "vision", {"owner_presence_probe": owner_payload},
        owner_probe_dir, WORKER,
    )
    owner_produced = owner_producer_probe["observed"]["owner_presence_probe"]
    for key in ("observation_status", "source_observation_id", "event_instances"):
        if owner_produced.get(key) != owner_payload[key]:
            raise RuntimeError(
                f"Vision producer did not preserve optional owner metadata {key}"
            )
    targets = owner_produced.get("human_candidates")
    if not isinstance(targets, list) or len(targets) != 1:
        raise RuntimeError("Vision producer did not preserve the owner candidate probe")
    for key in ("identity", "identity_state", "tracking_state", "target_id", "track_id", "vision_epoch"):
        if targets[0].get(key) != owner_payload["human_candidates"][0][key]:
            raise RuntimeError(f"Vision producer changed owner candidate field {key}")

    owner_control = deepcopy(owner_produced)
    owner_control["events"] = ["EVT_VISION_MASTER"]
    emotion_owner_probe = run_stage(
        "emotion",
        [
            {"id": "owner-event-control", "steps": [{"wire": json.dumps(owner_control, ensure_ascii=False)}]},
            {"id": "owner-event-metadata", "steps": [{"wire": json.dumps(owner_produced, ensure_ascii=False)}]},
        ],
        owner_probe_dir,
        WORKER,
    )
    owner_control_steps = emotion_owner_probe["observed"]["owner-event-control"]
    owner_metadata_steps = emotion_owner_probe["observed"]["owner-event-metadata"]
    state_fields = ("emotions", "demands", "owner_present")
    if (
        len(owner_control_steps) != 1
        or len(owner_metadata_steps) != 1
        or any(
            owner_control_steps[0].get(key) != owner_metadata_steps[0].get(key)
            for key in state_fields
        )
        or owner_control_steps[0]["accepted"][0]
        != owner_metadata_steps[0]["accepted"][0]
    ):
        raise RuntimeError(
            "EVT_VISION_OWNER_PRESENT changed EVT_VISION_MASTER Emotion/need output"
        )

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
    provenance = {stage: value["provenance"] for stage, value in responses.items()}
    provenance["facial_expression_probe"] = {
        "producer_module": producer_probe["provenance"]["module_file"],
        "emotion_module": emotion_probe["provenance"]["module_file"],
        "canonical_faces_checked": ["faces", "debug_faces"],
        "marsdog_emotion_unchanged": True,
    }
    provenance["owner_presence_probe"] = {
        "producer_module": owner_producer_probe["provenance"]["module_file"],
        "emotion_module": emotion_owner_probe["provenance"]["module_file"],
        "optional_v1_metadata_checked": [
            "observation_status", "source_observation_id", "event_instances",
        ],
        "owner_identity_tracking_fields_checked": True,
        "master_emotion_and_need_unchanged": True,
    }
    return ({stage: value["observed"] for stage, value in responses.items()}, provenance)


if __name__ == "__main__":
    sys.exit(check_main(FIXTURES, observe, ROOT / "out/visual-contracts"))
