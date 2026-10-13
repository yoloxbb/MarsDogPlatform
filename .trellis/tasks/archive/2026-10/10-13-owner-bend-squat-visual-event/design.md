# Design: owner bend/squat visual event

## Decision summary

- Add `EVT_VISION_OWNER_BEND_SQUAT` as a state event for the existing public `bend_over` and `squat_down` pose outputs. Preserve all current owner/family/stranger presence and emotion event paths.
- Keep `/perception/visual_event`, `std_msgs/msg/String`, and visual-event schema v1. Use the already supported `observation_status`, `source_observation_id`, `events[]`, and `event_instances` fields; no new topic, ROS type, required field, or baseline refresh.
- Vision owns posture qualification and the active event cycle. BehaviorTree owns target revalidation, candidate creation, event-instance deduplication, and L2 arbitration. Vision never dispatches an Action.
- Require a current source-frame target with `identity=owner`, `identity_state=confirmed_known`, `tracking_state=tracking`, matching positive track/target IDs and `vision_epoch`, and a public `pose_action` of `bend_over` or `squat_down`.
- Start event entry timing from the first distinct valid source observation with a stable public posture; use `T_enter=1.0s`. Ignore repeated 10 Hz snapshots with the same source observation ID. Do not add `T_retrigger` cooldown.
- Reuse the upstream GesturePose release rule: the active public posture label remains while at least 3/10 classifier updates meet score `>=0.50` and is released below 3/10. The event state rearms only on a distinct valid source observation from the same owner target after that public posture has cleared. There is no additional release timer. This tolerates transient misses without double-debouncing or adding a new unrelated threshold.
- Invalid/stale observations, failed inference, camera interruption, and duplicate source packets do not prove posture release. They preserve an active event ID; they cannot advance entry. A target ID or epoch change discards old pending/active state so no candidate can inherit another target's cycle.
- Add the event to the BehaviorTree visual-direct path with the existing social visual priority: category `external_interaction`, `priority_level=1`, `sub_priority=12`, `semantic_rank=3`, `modality_rank=2`, `interrupt_policy=safe_point`, and target freshness-bounded TTL. Revalidate the same owner target and current posture immediately before dispatch.
- Candidate mapping: `EVT_VISION_OWNER_BEND_SQUAT` → intent `owner_approach_response` → existing Behavior `approach_owner` → Action unit `ACT_INTERACT_APPROACH_OWNER_CLOSER`. This reuses only the registered owner-approach capability. `ACT_OWNER_APPROACH_RESPONSE` is not a registered Action unit; it remains the product candidate label, not a ROS event or executable unit.
- Do not add tail-wag or look-up stages. `ACT_WAG_TAIL` is an unverified Lite3 body-yaw proxy; `ACT_RAISE_HEAD` is an unverified completion-marker proxy; and `ACT_STOP_OBSERVE_AND_TILT_HEAD` is an unverified body-yaw proxy used for animal greeting, not owner-directed observation. These do not establish the requested physical responses. The candidate therefore performs the supported approach component only. Report that tail wag and an observation-oriented head-up response remain unsupported.

## Data flow

```text
current Vision inference
  → existing GesturePose per-track smoother
  → current owner target + pose_action bend_over|squat_down
  → owner posture event state (distinct source IDs, 1.0 s entry)
  → v1 events[] + event_instances[EVT_VISION_OWNER_BEND_SQUAT]
  → Behavior visual-event consumer (event_id dedup)
  → same-snapshot owner/posture target validation
  → owner_approach_response intent / approach_owner candidate
  → existing candidate pool and L2 multi-source arbitration
  → existing ExecuteBehavior / ACT_INTERACT_APPROACH_OWNER_CLOSER route
```

Emotion continues to consume its existing events. The new pose keys remain unmapped in Vision's emotion/action event table, and the new visual event is not an Emotion input.

## Vision state policy

Implement an owner posture-specific state helper rather than changing the defaults or semantics of owner/family/stranger presence states. Its configuration owns `enabled` and `enter_duration_sec` (default 1.0); source freshness follows the current 0.5 s camera-stale bound. A source key includes epoch and source observation ID, and posture continuity is bound to the same target ID and track ID.

On entry, distinct current owner observations with either accepted public posture advance the timer. At the threshold, allocate a cycle ID and publish the event. While either accepted posture remains active for that same target, keep the event and ID in every valid snapshot without creating another candidate. Once the existing smoother releases the pose, the next distinct valid same-target observation removes the event and ID and rearms immediately. Invalid observations preserve the active cycle and cannot count as a release. An epoch or target change clears that cycle and requires a fresh full entry interval for the new context.

## BehaviorTree policy

Treat the posture event as a state event in the existing presence-event consumer set so repeated HOLD snapshots and short cache outages retain one consumed ID. Extend event-specific qualification so both candidate construction and dispatch-time revalidation require the same snapshot's matching owner identity/tracking plus `pose_action ∈ {bend_over, squat_down}`. Candidate parameters retain `vision_epoch`, `snapshot_id`, `snapshot_sequence`, `source_observation_id`, event instance ID, active target, and visual header. Missing/ambiguous/stale target, event instance, posture, or epoch rejects the candidate.

The intent uses the existing `approach_owner` Behavior, whose Action template accepts a locked owner visual target. This creates only the explicitly requested approach reaction. Do not route to a generic social-affection template because its available tail unit is an unverified proxy, and do not treat the head-up completion marker as an observation behavior.

## Compatibility and rollback

- Existing `EVT_VISION_MASTER`, `EVT_VISION_MASTER_*`, `EVT_VISION_OWNER_PRESENT`, `EVT_VISION_FAMILY_PRESENT`, and `EVT_VISION_STRANGER_PRESENT` names, generation, priorities, and semantics remain unchanged.
- No Emotion mapping, state increment, or settlement is added.
- Keep the frozen visual-event v1 `baseline.json` byte-for-byte unchanged. Add separate producer/consumer probe coverage if the contract harness needs to exercise the new optional active-state instance.
- Update the Vision event contract, Behavior event map/candidate docs, and application visual-event v1 contract. Refresh the generated naming catalog only through its supported generator; make no blanket compatibility exception for unrelated identifiers.
- Rollback removes the posture state/config/event path and its Behavior mapping/tests/docs. No ROS interface migration or persistent data migration is required.

## Risks and limits

- Entry timing starts after the existing GesturePose smoothing has selected the public posture; total time from raw classifier scores may exceed 1.0 s. The event's configured `T_enter` remains exactly 1.0 s over distinct public-pose observations.
- The current supported Action response is approach only. It remains subject to its existing current-target, safety, controller, cancellation, and navigation checks. Tail wag and an observation-oriented look-up are not claimed.
- Full runtime and robot hardware behavior are outside the pure-contract acceptance scope; software tests must remain isolated from production ROS domains and hardware.
