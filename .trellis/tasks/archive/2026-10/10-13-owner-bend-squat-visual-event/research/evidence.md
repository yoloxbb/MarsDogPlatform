# Owner bend/squat visual event: repository evidence

## Governing records reviewed

- Root `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, and `docs/development/WORKFLOW.md`.
- Vision migration records `docs/migration/P4_VISION.md` and `P4_VISION_PREFLIGHT.md`; Behavior and Action records `P3_BEHAVIOR.md` and `P3_ACTION.md`.
- `interfaces/application/visual-event-v1/README.md`, `interfaces/application/README.md`, `interfaces/registry.json`, and `interfaces/naming/README.md`.
- Vision's existing owner/family/stranger presence specs and GesturePose spec under `.trellis/spec/backend/`.
- Archived Trellis tasks `10-13-pet-attention-postures`, `10-12-vision-owner-greet`, and `10-12-family-stranger-presence`.

## Vision facts

- Commit `0595dd2` added public posture actions `bend_over` and `squat_down` in Vision. Their existing GesturePose temporal policy is a 10-update window: activation at 6/10 scores `>=0.50`; active labels remain while at least 3/10 scores meet that threshold and release below 3/10. The public keys are `active_target.pose_action` and the matching current `human_candidates[].pose_action`. No event mapping or emotion mapping exists for those keys.
- The Vision source frame carries `_source_observation_id`, source age, validity, and current source owner-target IDs. `VisionInteractionNode` marks the whole snapshot `observation_status=invalid` when the provider/camera/source evidence is invalid or stale. It publishes at 10 Hz, while a repeated source observation retains the same source ID.
- The v1 packet already supports `observation_status`, `source_observation_id`, and `event_instances.<event>.event_id` as optional fields. `_apply_presence_event_states` keeps an active event in `events[]` through HOLD and removes it on release. No ROS type, topic, required field, or schema version needs to change.
- Existing generic presence configuration uses 1.0 s entry, 2.0 s exit, and 3.0 s retrigger. The posture requirement explicitly disallows that generic cooldown; the new posture cycle must use its own state policy and immediately rearm on a valid stabilized posture release.
- The current source freshness bound is the camera stale timeout (0.5 s default). Invalid observations preserve active state and break pending timing continuity in the existing state-event pattern.

## BehaviorTree facts

- `/perception/visual_event` is parsed as v1 and cached with epoch, snapshot ID/sequence, source observation ID, event names, instances, and human candidates.
- Existing state-event consumers deduplicate by event instance ID across repeated HOLD packets and brief cache/topic gaps. Candidate creation and pre-dispatch revalidation require exactly one fresh matching target in the same epoch and current snapshot; candidate TTL is bounded by the 500 ms target freshness window.
- Existing social visual candidates use `external_interaction` (`priority_level=1`), `sub_priority=12`, `semantic_rank=3`, `interrupt_policy=safe_point`, and visual modality rank 2. This is the non-safety L2 path.
- To make posture candidate context safe, the new route must additionally require the same target's current `pose_action` to remain `bend_over` or `squat_down` at mapping and immediately before dispatch.

## Behavior / Action mapping facts

- The product label `ACT_OWNER_APPROACH_RESPONSE` is not registered as an Action unit or Behavior template. Naming rules keep `EVT_*`, lowercase `intent`/`behavior_name`, and `ACT_*` unit IDs in distinct namespaces.
- The existing BT Behavior `approach_owner` has an Action template with `ACT_INTERACT_APPROACH_OWNER_CLOSER`; Action routes that unit through `person_nav_approach`. This implements the approach-owner portion and requires a locked current visual target.
- `ACT_WAG_TAIL` is a registered unit, but the Lite3 implementation is an unverified body-yaw proxy, not a confirmed tail movement. `ACT_RAISE_HEAD` is an unverified posture proxy used as a completion marker. `ACT_STOP_OBSERVE_AND_TILT_HEAD` is used by an animal-greeting template, but its Lite3 implementation is also an unverified body-yaw proxy, not an owner-directed look-up. No registered behavior combines these units with owner approach as the requested response.
- Therefore the product candidate can map to existing `approach_owner` only for the approach component. Tail wag and looking up to observe the owner remain unavailable as semantically verified parts of this response. Do not create a composite Action template or claim those effects.

## Contract and validation facts

- `tools/check_visual_contracts.py` reads a frozen `cases.json`/`baseline.json` corpus and also runs separate optional probes for newer v1 metadata. The baseline must remain byte-for-byte frozen; add any new probe separately.
- Existing Vision/Behavior tests cover the presence-state and event-candidate boundaries in the respective module test trees. Naming checks use `interfaces/naming/compatibility_exceptions.json` for intentionally unsupported Action templates; new candidate mapping must be represented without suppressing unrelated identifier errors.
- No production ROS domain, camera, or hardware is needed for the required state, mapper, consumer, and contract tests.
