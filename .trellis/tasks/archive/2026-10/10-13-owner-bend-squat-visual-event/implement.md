# Implementation plan: owner bend/squat visual event

## Start gate

This is a complex cross-module task. Review the planning summary and explicitly approve it in a later message before running `task.py start` or editing product code. The current candidate mapping is approach-only; tail wag and look-up observation are not claimed.

## Ordered work

1. **Load execution context.** After approval, load `trellis-before-dev` for Vision and Behavior backend work. Read this task's manifests/artifacts, `.trellis/spec/backend/vision-owner-presence-event.md`, `vision-human-presence-events.md`, `vision-gesture-pose.md`, the shared cross-layer guide, and the required root/project records. Confirm task scope and current branch before edits.

2. **Implement owner-posture cycle in Vision.** Add the independent `EVT_VISION_OWNER_BEND_SQUAT` event state and a root config section with `enabled` and `enter_duration_sec=1.0`. Consume current source IDs only; require owner/confirmed-known/tracking on the same target and current epoch; accept existing public `pose_action` values `bend_over` and `squat_down`. Advance only on distinct valid source observations. Keep one event instance active through HOLD. Reuse GesturePose's existing release hysteresis (active at 3/10 votes, released below 3/10) and rearm immediately on a valid same-target observation after the public pose clears. Add no retrigger cooldown and no second release threshold. Preserve active state across invalid/stale inference and duplicate packets; reset target/epoch-bound evidence so no old cycle transfers to a new target.

3. **Integrate and test Vision publication.** Merge the event through the existing v1 state-event publisher and ensure its ID is removed with the event on release. Add pure state and node/normalizer tests for identity gates, current target binding, stable entry boundary, duplicate snapshots, one ENTER/HOLD, posture switch while held, release/rearm, transient missed posture frames, camera/inference invalidity, stale data, stream recovery, target switch, and epoch changes. Assert no new emotion event or event mapping is generated and existing owner/family/stranger events are unchanged.

4. **Route the candidate through BehaviorTree.** Add `EVT_VISION_OWNER_BEND_SQUAT` to the state-event/direct visual path and event-specific owner/posture qualifiers. Map it to intent `owner_approach_response` and existing Behavior `approach_owner`; preserve its actual Action unit `ACT_INTERACT_APPROACH_OWNER_CLOSER`. Use the social visual L2 settings (`priority_level=1`, `sub_priority=12`, `semantic_rank=3`, `modality_rank=2`, `safe_point`, TTL bounded by the 500 ms target freshness). Carry event ID, owner target, epoch, snapshot/sequence, source observation ID, and header. Require the same current posture/target both when creating the candidate and immediately before dispatch. Keep the generic direct-event edge behavior and all existing presence routes unchanged.

5. **Add Behavior and cross-layer contract tests.** Cover owner-only identity, familiar/stranger/unconfirmed/non-tracking rejection; duplicate source packet and event-instance dedup; short cache/topic interruption recovery; new ID only after release/rearm; posture, target, snapshot and epoch revalidation; candidate entering the existing pool/arbitration at the intended L2 order; and no direct Vision-to-Action call or Emotion effect. Extend visual contract metadata probes separately from the frozen baseline if needed. Verify the route resolves only to `approach_owner` / `ACT_INTERACT_APPROACH_OWNER_CLOSER`; never add an Action template for `ACT_OWNER_APPROACH_RESPONSE` or unverified wag/head proxies.

6. **Update contracts and docs.** Update Vision `ROS2_CONTRACT.md` and test guidance, Behavior event routing/catalog/handoff docs, and `interfaces/application/visual-event-v1/README.md`. Document event name, owner/pose gates, 1.0 s entry, source dedup, inherited 3/10 posture release rule, invalid-observation semantics, active `events[]`/event ID behavior, candidate dedup and L2 path, actual approach mapping, and missing physical tail-wag/look-up capability. Preserve the event registry endpoint, v1 required fields, and frozen baseline. Refresh generated identifier catalog only through the prescribed tool.

7. **Run required verification.** Run from repository root:

   ```bash
   python3 tools/dev.py check
   python3 tools/dev.py test vision
   python3 tools/dev.py test behavior
   python3 -B tools/check_visual_contracts.py
   python3 -B tools/check_identifiers.py --refresh --python modules/action/.venv/bin/python
   python3 -B tools/check_identifiers.py --live --python modules/action/.venv/bin/python
   ```

   Keep pure test results separate from any isolated ROS transport report. Do not connect to cameras, hardware, or production ROS domains. Report skipped tests as skipped, never as passes; do not refresh `interfaces/application/visual-event-v1/baseline.json`.

8. **Review and finish.** Inspect the full diff for unchanged existing owner/familiar/stranger/emotion event semantics, unchanged endpoint/type/required fields, no Emotion mapping, no new motion protocol, and no unrelated edits. Capture exact entry/release policy and Action limitations in the final report. Update the relevant Trellis spec if implementation reveals a reusable owner-posture event contract; then run the Trellis quality check and finish workflow before commit/archive.

## Risk and rollback points

- **Vision state integration:** the existing publisher derives legacy events before state events. Merge the new event without changing event order or existing IDs; roll back the state helper, config, and focused tests together.
- **Behavior revalidation:** extend posture checks only for the new event. Preserve the current owner/family/stranger qualifications and lifecycle. If the current pose is stale or absent before dispatch, reject the unstarted candidate and preserve Action cancellation ownership.
- **Action semantics:** `approach_owner` is executable; the full response is not. Keep only that existing stage. Do not turn proxy labels into claims that the tail or head moved.
- **Contract baseline:** add new probe coverage beside the frozen corpus. Any baseline diff is a stop-and-investigate condition, not permission to regenerate it.
