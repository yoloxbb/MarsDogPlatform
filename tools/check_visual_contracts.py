"""Verify Vision -> BT/Emotion/Action using the pre-refactor wire corpus."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from contract_harness import ROOT, check_main, run_stage, write_json

FIXTURES = ROOT / "interfaces/application/visual-event-v1"
WORKER = ROOT / "integration/contracts/visual_stage.py"


def _validate_owner_posture_action_resolution(resolution):
    expected = {
        "is_valid": True,
        "behavior_name": "approach_owner",
        "unit_ids": ["ACT_INTERACT_APPROACH_OWNER_CLOSER"],
        "units_registered": True,
        "controller_routes": {"lite3": ["person_nav_approach"], "go2": ["person_nav_approach"]},
        "product_label_registered": False,
    }
    if resolution != expected:
        raise RuntimeError("Owner posture candidate changed its registered Action mapping")


def _owner_posture_probe(output, owner_payload):
    """Check the new event beside the immutable required-v1 corpus."""
    event = "EVT_VISION_OWNER_BEND_SQUAT"
    probe_dir = output / "owner-posture-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(owner_payload)
    payload["events"] = ["EVT_VISION_MASTER", event]
    payload["event_instances"] = {event: {"event_id": "owner-posture-probe-cycle-1"}}
    payload["human_candidates"][0]["pose_action"] = "bend_over"
    producer = run_stage("vision", {"owner_posture": payload}, probe_dir, WORKER)
    produced = producer["observed"]["owner_posture"]
    for field in ("events", "event_instances", "source_observation_id", "observation_status"):
        if produced.get(field) != payload[field]:
            raise RuntimeError(f"Vision changed owner posture metadata {field}")
    if produced["human_candidates"][0].get("pose_action") != "bend_over":
        raise RuntimeError("Vision lost the owner posture target context")

    wire = json.dumps(produced, ensure_ascii=False)
    repeated = deepcopy(produced)
    repeated.update(snapshot_id="owner-probe-epoch:2", sequence=2)
    behavior = run_stage("behavior", [{"id": "posture", "steps": [
        {"wire": wire}, {"wire": json.dumps(repeated, ensure_ascii=False)},
        {"advance": 1.1, "wire": json.dumps({**repeated, "snapshot_id": "owner-probe-epoch:3", "sequence": 3}, ensure_ascii=False)},
    ]}], probe_dir, WORKER)
    steps = behavior["observed"]["posture"]
    if any(step["error"] for step in steps) or len(steps[0]["candidates"]) != 1:
        raise RuntimeError("Owner posture did not produce exactly one Behavior candidate")
    candidate = steps[0]["candidates"][0]
    if (
        candidate["behavior_name"] != "approach_owner"
        or candidate["intent"] != "owner_approach_response"
        or candidate["source"] != "visual_direct"
        or candidate["priority_level"] != 1
        or candidate["semantic_rank"] != 3
        or candidate["sub_priority"] != 12
        or candidate["modality_rank"] != 2
        or candidate["interrupt_policy"] != "safe_point"
        or candidate["params"]["visual_event_instance_id"] != "owner-posture-probe-cycle-1"
        or any(step["candidates"] for step in steps[1:])
    ):
        raise RuntimeError("Owner posture bypassed its intended L2 mapping or instance dedup")

    control = deepcopy(produced)
    control["events"] = ["EVT_VISION_MASTER"]
    emotion = run_stage("emotion", [
        {"id": "control", "steps": [{"wire": json.dumps(control, ensure_ascii=False)}]},
        {"id": "posture", "steps": [{"wire": wire}]},
    ], probe_dir, WORKER)
    control_step = emotion["observed"]["control"][0]
    posture_step = emotion["observed"]["posture"][0]
    # Needs returns every input event name as receipt metadata. Compare its
    # state and the Emotion consumer's applied events, not that receipt list.
    if (
        any(control_step[field] != posture_step[field]
            for field in ("emotions", "demands", "owner_present"))
        or control_step["accepted"][0] != posture_step["accepted"][0]
    ):
        raise RuntimeError("Owner posture event changed Emotion/Needs output")

    action = run_stage("action", [{"id": "posture", "steps": [{
        "wire": wire, "resolve_behavior": candidate["behavior_name"],
    }]}], probe_dir, WORKER)
    action_step = action["observed"]["posture"][0]
    _validate_owner_posture_action_resolution(action_step["resolution"])
    expected_ports = ["attention_controller", "target_approach_adapter", "visual_target_approach_adapter",
                      "wake_orientation_adapter", "person_nav_approach_adapter"]
    if (
        action_step["accepted"] is not True
        or [delivery["port"] for delivery in action_step["delivery_order"]] != expected_ports
        or any(delivery["payload"] != produced for delivery in action_step["delivery_order"])
    ):
        raise RuntimeError("Owner posture visual packet changed Action's observation-only fan-out")
    return {
        "producer_module": producer["provenance"]["module_file"],
        "behavior_module": behavior["provenance"]["module_file"],
        "emotion_module": emotion["provenance"]["module_file"],
        "action_module": action["provenance"]["module_file"],
        "event_name": event,
        "behavior": "approach_owner",
        "action_unit": "ACT_INTERACT_APPROACH_OWNER_CLOSER",
        "emotion_and_need_unchanged": True,
        "instance_dedup_across_cache_timeout": True,
        "scope": "candidate and registered resolver checks; observation-only Action ports; no motion execution",
    }


def _owner_recall_probe(output, owner_payload):
    """Check recall event routing without changing the frozen v1 corpus."""
    event = "EVT_VISION_OWNER_RECALL_GESTURE"
    probe_dir = output / "owner-recall-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(owner_payload)
    payload["events"] = ["EVT_VISION_MASTER", event]
    payload["event_instances"] = {event: {"event_id": "owner-recall-probe-cycle-1"}}
    producer = run_stage("vision", {"owner_recall": payload}, probe_dir, WORKER)
    produced = producer["observed"]["owner_recall"]
    for field in (
        "events", "event_instances", "source_observation_id", "observation_status",
        "vision_epoch", "snapshot_id", "sequence",
    ):
        if produced.get(field) != payload[field]:
            raise RuntimeError(f"Vision changed owner recall metadata {field}")
    produced_targets = produced.get("human_candidates")
    if not isinstance(produced_targets, list) or len(produced_targets) != 1:
        raise RuntimeError("Vision producer did not preserve the owner recall target")
    for field in (
        "identity", "identity_state", "tracking_state", "target_type", "target_id",
        "track_id", "vision_epoch", "last_seen_age_ms",
    ):
        if produced_targets[0].get(field) != payload["human_candidates"][0][field]:
            raise RuntimeError(f"Vision changed owner recall target field {field}")

    wire = json.dumps(produced, ensure_ascii=False)
    repeated = deepcopy(produced)
    repeated.update(snapshot_id="owner-probe-epoch:2", sequence=2)
    behavior = run_stage("behavior", [{"id": "recall", "steps": [
        {"wire": wire},
        {"wire": json.dumps(repeated, ensure_ascii=False)},
        {"advance": 1.1, "wire": json.dumps({
            **repeated, "snapshot_id": "owner-probe-epoch:3", "sequence": 3,
        }, ensure_ascii=False)},
    ]}], probe_dir, WORKER)
    steps = behavior["observed"]["recall"]
    if any(step["error"] for step in steps) or len(steps[0]["candidates"]) != 1:
        raise RuntimeError("Owner recall did not produce exactly one Behavior candidate")
    candidate = steps[0]["candidates"][0]
    target = candidate.get("target", {})
    if (
        candidate["behavior_name"] != "approach_owner"
        or candidate["intent"] != "owner_approach_response"
        or candidate["source"] != "visual_direct"
        or candidate["trigger_event"] != event
        or candidate["priority_level"] != 1
        or candidate["semantic_rank"] != 3
        or candidate["sub_priority"] != 12
        or candidate["modality_rank"] != 2
        or candidate["interrupt_policy"] != "safe_point"
        or candidate["source_emotion"]
        or candidate["params"]["visual_event_instance_id"] != "owner-recall-probe-cycle-1"
        or candidate["params"]["snapshot_id"] != payload["snapshot_id"]
        or candidate["params"]["source_observation_id"] != payload["source_observation_id"]
        or target.get("target_id") != payload["human_candidates"][0]["target_id"]
        or target.get("vision_epoch") != payload["vision_epoch"]
        or any(step["candidates"] for step in steps[1:])
    ):
        raise RuntimeError("Owner recall bypassed L2 mapping, fresh target, or instance dedup")

    control = deepcopy(produced)
    control["events"] = ["EVT_VISION_MASTER"]
    emotion = run_stage("emotion", [
        {"id": "control", "steps": [{"wire": json.dumps(control, ensure_ascii=False)}]},
        {"id": "recall", "steps": [{"wire": wire}]},
    ], probe_dir, WORKER)
    control_step = emotion["observed"]["control"][0]
    recall_step = emotion["observed"]["recall"][0]
    # Needs returns every input event as receipt metadata. Compare its state,
    # owner-presence state, and the Emotion consumer's applied events.
    if (
        any(control_step[field] != recall_step[field]
            for field in ("emotions", "demands", "owner_present"))
        or control_step["accepted"][0] != recall_step["accepted"][0]
    ):
        raise RuntimeError("Owner recall changed Emotion/Needs output")

    action = run_stage("action", [{"id": "recall", "steps": [{
        "wire": wire, "resolve_behavior": candidate["behavior_name"],
    }]}], probe_dir, WORKER)
    _validate_owner_posture_action_resolution(
        action["observed"]["recall"][0]["resolution"]
    )
    return {
        "producer_module": producer["provenance"]["module_file"],
        "behavior_module": behavior["provenance"]["module_file"],
        "emotion_module": emotion["provenance"]["module_file"],
        "action_module": action["provenance"]["module_file"],
        "event_name": event,
        "behavior": "approach_owner",
        "action_unit": "ACT_INTERACT_APPROACH_OWNER_CLOSER",
        "emotion_and_need_unchanged": True,
        "instance_dedup_across_repeated_snapshots_and_cache_timeout": True,
        "scope": "shared candidate/L2 route and registered resolver; no direct motion execution",
    }


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

    owner_posture_provenance = _owner_posture_probe(output, owner_payload)
    owner_recall_provenance = _owner_recall_probe(output, owner_payload)

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
    provenance["owner_posture_probe"] = owner_posture_provenance
    provenance["owner_recall_probe"] = owner_recall_provenance
    return ({stage: value["observed"] for stage, value in responses.items()}, provenance)


if __name__ == "__main__":
    sys.exit(check_main(FIXTURES, observe, ROOT / "out/visual-contracts"))
