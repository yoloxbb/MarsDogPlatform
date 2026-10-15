# Implementation plan: visible-toy state event

## Start gate

This is a cross-module behavior change. The user approved the product decisions to preserve all detector activation settings and reuse `EVT_VISION_TOY` for stable visible toys. Review this planning summary and explicitly approve it in a later message before `task.py start` or product-code edits.

## Ordered work

1. **Load implementation context.** After approval, run the Trellis start/continue workflow and `trellis-before-dev` for Vision, Behavior and Emotion. Re-read current root instructions, requested migration/contract/Behavior/Emotion/Action documents, relevant specs and current branch/status. Verify no repository change invalidated the planning evidence.

2. **Implement pure Vision toy presence state.** Add a scene-level helper/config with defaults `enter_duration_sec=1.0`, `exit_duration_sec=2.0`, `retrigger_sec=3.0`. Inputs must include result status, existing label request scope, detections, source observation identity/time, epoch and freshness. Count only distinct fresh source observations. Positive supported-label detections use the existing task confidence path; empty results count negative only when the valid request scope covers all three supported toy labels. Unknown and stale observations do not advance timers; stale continuity restarts pending entry/exit while preserving a published active ID. Handle source ordering and epoch restart fail-closed.

3. **Wire Vision state into the existing v1 publisher.** Feed the manager from the object-result producer/callback so one-shot, configured continuous, and the existing held stream can contribute when they already run. Do not start or speed up any stream. Serialize the same active `EVT_VISION_TOY` and event ID on HOLD; remove both on EXIT. Remove the unstable direct `holding_toy` event edge while retaining all nested `held_object` data and existing non-toy event mappings. Keep schema v1 required fields and frozen baseline unchanged.

4. **Add Vision tests.** Pure state/producer/contract tests cover: no entry before 1 second; exactly one entry and ID at threshold; same source packet replay and 10 Hz serialization do not progress; repeated boxes/multiple toys share one scene event; positive jitter and short valid negative misses; exit at 2 seconds only on complete effective negatives; 3-second cooldown followed by a full new entry; narrow label-filter negative unknown; inference failure/invalid status/stale results/camera outage preserve active event and do not advance pending durations; epoch/order handling; unheld toy acceptance; held-object fields preserved; and other existing visual events unchanged.

5. **Route one Behavior candidate.** Add the toy event to the visual direct allowlist without adding it to human presence gates. Add a separate object-event instance dedupe path keyed by `event_id`, same-snapshot supported target selection, fresh target validation and one candidate per cycle. Map event → `toy_found_play` intent → `inspectFamiliarPlayItem`, carry candidate product label `ACT_TOY_FOUND_PLAY`, and configure external-interaction L2 ranks/priority/safe-point TTL. Ensure all candidates still enter the shared source arbiter; no Vision-to-Action direct call.

6. **Add Behavior tests.** Cover event name and event-instance requirement; one candidate on initial ID only across HOLD, repeated frames, duplicate boxes, cache recovery and several visible toys; a new candidate only for a new post-cooldown ID; same-snapshot label/target binding; no human identity gate; no candidate/dispatch for invalid, missing, stale, mismatched or ambiguous toy targets; correct intent/Behavior/product label/L2 metadata and candidate pool; arbitration against other sources; no action success without target metric data; and unchanged fall/stop/human presence/posture/gesture routes.

7. **Add Emotion per-cycle deduplication.** Preserve the existing `EVT_VISION_TOY` emotion deltas/personality scaling. Apply once per event ID, independent of HOLD duration and the generic same-name 10-second window; allow distinct IDs as distinct cycles. Preserve compatibility for v1 event payloads that lack `event_instances`. Test held and unheld visibility as one event stream, repeated HOLD past ten seconds, repeated same ID, new ID within the old debounce window, duplicate event strings and legacy payload behavior.

8. **Update contract and module documentation.** Update Vision event production/label/detection activation and accepted no-person limitation; Behavior visual direct mapping, L2 route and candidate dedupe; Emotion existing toy mapping/once-per-cycle semantics; Action behavior map with target-depth limitation; and application `visual-event-v1` lifecycle. Preserve all standard detection configs and required schema fields. Refresh `interfaces/naming/catalog.json` with its supported generator only if source YAML changes require it; never refresh the visual contract baseline.

9. **Run required verification.** Run:

   ```bash
   python3 tools/dev.py check
   # Run the documented test command for each impacted module: vision, behavior, emotion.
   python3 -B tools/check_visual_contracts.py
   # If identifier-owning YAML changed, regenerate/check its catalog using the
   # repository-prescribed identifier command and Action module Python.
   ```

   Use the test matrix in `docs/development/WORKFLOW.md` for the exact affected module commands. Keep pure logic results separate from real ROS transport results. Never connect to hardware or a production ROS domain; report skips as skips, not passes.

10. **Review and finish.** Inspect diff for standard config frequency changes, other-object behavior, accidental human gates, event ID duplication, schema required-field/baseline changes, unsupported Action claims, and existing visual event regressions. Update task acceptance checklist and relevant Trellis specs if implementation reveals a reusable invariant. Run the Trellis check/finish workflow; do not commit/archive without the user's instruction.

## Main rollback points

- Vision state callback and event serialization can be removed together while preserving the previous v1 topic and all `held_object` fields.
- Behavior direct route, object-cycle consumer/dedupe and candidate pool entries can be reverted without affecting the existing human presence/direct visual event sets.
- Emotion event-ID tracking can be isolated to `EVT_VISION_TOY`, leaving other emotion debouncing untouched.
- If current detector results cannot prove source freshness or complete negative label coverage, that path must yield unknown; do not infer EXIT from it.
- If there is no valid metric object range, existing Action must refuse approach. Record this as an execution limitation rather than adding a distance estimate or success fallback.
