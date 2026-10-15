# Design: stable visible-toy event

## Decision summary

- Reuse `EVT_VISION_TOY`; its public meaning becomes “at least one stable, visible supported toy.” A held toy is still included, while the existing `held_object` observation remains intact. The toy event has one producer and one scene-level cycle, so held and unheld paths cannot emit parallel toy events.
- Keep `/perception/visual_event`, `std_msgs/msg/String`, schema v1 and its required fields. Publish the active event name in `events[]` and one stable `event_instances.EVT_VISION_TOY.event_id` during HOLD. On EXIT, remove both. No ROS endpoint/type change and no frozen baseline refresh.
- Vision owns object-evidence qualification and ENTER/HOLD/EXIT. Behavior owns candidate deduplication, same-snapshot target binding, and L2 arbitration. Emotion owns per-event-cycle emotion deduplication. Vision does not select an action or dispatch it.
- The only eligible labels are existing provider labels `dog toy ball`, `dog frisbee toy`, and `dog tug ring toy`, defined by the existing held-object toy label set. This is a scene-level “one or more toys” state, not per-box/per-track state.
- Preserve current detection activation. The standard config has 0 Hz continuous object inference; its restricted 2 Hz held-object stream starts only while a human is tracked. A one-shot or configured continuous request may also feed the same state machine. With no human and no other active detection session there are no observations, so autonomous discovery is unavailable; no frequency/resource decision is hidden in this change.
- Defaults are configurable `T_enter=1.0s`, `T_exit=2.0s`, `T_retrigger=3.0s` (within the requested 3–5 s range). Timing advances only on distinct, fresh source object observations, not the 10 Hz visual serializer.
- The Behavior candidate carries product label `ACT_TOY_FOUND_PLAY` as candidate metadata and uses an internal intent such as `toy_found_play`. That string is not an Action `unit_id`. Reuse the registered `inspectFamiliarPlayItem` Behavior and its existing Action template; the final supported unit remains controlled by its current random/selection policy and safety gates.

## Data flow and ownership

```text
existing object inference task/result
  → filter existing supported toy labels
  → scene-level toy state (distinct source observations)
  → v1 events[] + one event_instances[EVT_VISION_TOY].event_id
  ├─→ Emotion: existing toy mapping once per event_id
  └─→ Behavior visual-event consumer: first event_id only
        → current tracked toy target from this snapshot
        → toy_found_play / inspectFamiliarPlayItem candidate
        → existing L2 candidate pool and multi-source arbitration
        → existing Action target validation and execute/cancel lifecycle
```

The Vision result callback is the state-machine input, because it has the actual object inference status, source image identity/time, task label scope, and detections. Snapshot assembly serializes the current state but must not advance it. Repeated visual snapshots therefore repeat the same active event ID only; they cannot satisfy entry/exit durations.

## Vision evidence and state policy

### Effective observations

- Use the existing task/provider result and its configured confidence handling. Do not add a second generic confidence threshold. The restricted held-object flow keeps its existing `held_pose_confidence`; other detector requests keep their existing task threshold.
- Treat `(vision_epoch, source image timestamp/frame ID)` or the existing source observation identity as the observation key. A retry, repeated result, duplicate box, or another 10 Hz snapshot for the same source image does not advance time. When the source lacks an explicit observation ID, derive it only from the already available frame metadata; do not use the serializer sequence as a substitute for new camera evidence.
- A successful, fresh result containing any supported toy label is positive even if the task was label-filtered. A negative result is effective only if its requested label scope is unfiltered or includes all three supported toy labels. An empty result from a narrower request cannot prove that the scene has no toy.
- Failed/stopped object inference, malformed object results, results older than the existing object freshness/cache bounds, camera interruption, and incomplete negative label coverage are unknown. Unknown cannot advance entry or exit. For a pending entry/exit, an evidence gap beyond the existing freshness continuity bound restarts that pending duration; an active cycle and its ID survive unknown periods until valid negative evidence completes EXIT. The top-level v1 `observation_status` retains its existing human-provider meaning; it does not qualify or invalidate an independent object result.

### State transitions

- **Absent → EnterPending:** first distinct effective positive observation records the source observation time. Continue only on fresh, distinct positive observations. When their valid observation-time span reaches `T_enter`, allocate a unique cycle ID and publish `EVT_VISION_TOY`.
- **Active/HOLD:** continue publishing the same event name and event ID. Further positive observations, other simultaneous toy labels, and additional boxes do not create another cycle or event candidate. Unknown evidence keeps the active cycle but does not count as positive or negative.
- **Active → ExitPending:** first distinct effective negative observation records the negative interval. Fresh distinct effective negative observations advance it. A positive observation cancels pending exit. When the negative observation-time span reaches `T_exit`, remove the event and ID; EXIT itself never creates a Behavior candidate.
- **Exited/CoolingDown:** record exit time. Ignore positives for re-entry until `T_retrigger` has elapsed. Then reset entry evidence and require a new full `T_enter` interval before another event ID is published.
- Keep times on the monotonic/source observation timeline already used for inference age checks; reject out-of-order/duplicate evidence. If a camera restart changes epoch, do not count old-source evidence toward new entry/exit. Preserve an already published cycle as unknown until a fresh new-epoch valid negative sequence establishes EXIT.

Only the state-machine publisher emits `EVT_VISION_TOY`. Remove/disable the direct `holding_toy → EVT_VISION_TOY` appearance-edge emission so it cannot bypass stability, but continue filling the existing `held_object` fields and using held-object evidence as input to the common toy state when its source observation is valid. All unrelated special action event mappings remain unchanged.

## Behavior candidate and arbitration

- Add `EVT_VISION_TOY` to the direct visual allowlist, but keep it outside human presence sets and their identity/track gates. Require schema v1, the active event instance ID, and a fresh supported object row from the current serialized scene. Do not gate on top-level `observation_status`, which describes the human provider. A changed event ID is a new candidate; repeated HOLD IDs and cache recovery for the same ID are deduplicated.
- Bind the candidate to one current supported toy target from `tracked_objects` in the same snapshot. If several toys are visible, choose deterministically (highest existing detector confidence, then stable label/track tie-break); do not create one candidate per box. Do not infer target depth or distance. If the event is active but no fresh target can be bound, do not dispatch a targetless inspection behavior.
- Add `toy_found_play` to the existing visual direct route and candidate pool, with candidate metadata `product_action_label=ACT_TOY_FOUND_PLAY`. Use `category=external_interaction` (`priority_level=1`), `semantic_rank=3`, `sub_priority=12`, `modality_rank=2`, `interrupt_policy=safe_point`, and a TTL bounded by the current object target freshness. This remains a normal candidate in the existing source arbiter, so audio, touch, need, emotion and safety sources can win according to configured policy.
- Map the internal intent to registered `inspectFamiliarPlayItem`. Its actual Action template first needs `ACT_APPROACH_VISUAL_TARGET`; later it selects among already registered inspect/carry/sniff/paw/play-adjacent units. No new Action unit or forced final choice is introduced. Candidate creation is not proof of execution success.

## Emotion and compatibility

- Preserve `EVT_VISION_TOY` mapping values Excite +30, Curious +20, Joy +15 and its existing personality scaling.
- For event payloads with `event_instances`, pass the toy `event_id` into Emotion handling and keep a process-level bounded set/cache of applied IDs. Repeated snapshots for one cycle cannot reapply even after the existing 10-second same-name debounce period. A distinct new cycle ID can apply once independently of that debounce. Keep current legacy handling for old v1 payloads that contain the event name but no event instance.
- Emotion must not also receive a second held-toy event: the common Vision state publishes one `EVT_VISION_TOY` for held and unheld toy visibility. Keep the `held_object` nested data and unrelated human presence emotion events unchanged.
- Retain all existing schema required fields and event array types. Optional event instance data already belongs to v1; add no new required data and do not regenerate `interfaces/application/visual-event-v1/baseline.json`.

## Action boundary and accepted limitation

The existing `inspectFamiliarPlayItem` template is the only verified behavior route for this product request. Its approach phase has a real target-range requirement and current Vision object records often expose only 2D boxes (`range_valid=false`). Keep Action's fail-closed range/freshness behavior. Do not synthesize 3D coordinates, claim an approach or play action succeeded, or add unsupported sniff/carry execution. The software event/candidate can be complete while hardware execution remains unavailable for detections without valid metric depth.

## Documentation and rollback

Update Vision toy labels/state/detection limits and event manifest; the visual-event v1 contract; Behavior route, candidate, dedup and L2 docs; Emotion mapping/dedup docs; and Action capability/target limitation docs. Keep docs aligned with the unchanged standard detector activation rates. Update the generated identifier catalog only through its generator when source route configuration changes.

Rollback removes the toy state helper/config and its publisher integration, the Behavior route/consumer branch, Emotion event-ID dedupe, focused tests and corresponding docs. No persistent data, ROS endpoint, model, or Action protocol migration is introduced.

## Risks to verify during implementation

- Reconcile the current holding-toy event producer with the new common producer without dropping held-object observation details or retaining an unstable second event path.
- Confirm every active result path reports task label scope and source frame identity; if a source cannot prove a complete negative label scope, treat its empty result as unknown.
- Keep Vision positive recognition unblocked by human identity while leaving the existing human-event semantics untouched.
- Ensure the Behavior candidate reaches the candidate pool once per event ID and still passes the real target freshness/depth checks before execution.
