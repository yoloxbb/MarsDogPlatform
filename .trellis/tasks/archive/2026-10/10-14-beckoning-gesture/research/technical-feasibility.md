# Research: Beckoning gesture technical feasibility

- Query: Can the current GesturePose pipeline distinguish a palm toward the subject with repeated inward finger curls and expose a new pose_action without new ROS events?
- Scope: Internal source, contracts, tests, and checked-in backend documentation; no external algorithm or model accuracy claims.
- Date: 2026-10-14

## Findings

### Existing data and extension points

| File | Role and evidence |
| --- | --- |
| `modules/vision/marsdog_vision_interaction/providers/gesture_pose_engine.py` | Framework-independent per-person features, rule scoring, conflicts, smoothing, and 30-observation landmark history. |
| `modules/vision/marsdog_vision_interaction/providers/pose_action.py` | Per-track engine lifecycle, public pose/hand projection, debug diagnostics. |
| `modules/vision/marsdog_vision_interaction/providers/vision_observation.py` | Hand backend conversion and current-target pipeline integration. |
| `modules/vision/marsdog_vision_interaction/providers/hand_backends/base.py` | Shared 21x3 finite landmark and handedness output contract. |
| `modules/vision/marsdog_vision_interaction/providers/hand_backends/mediapipe.py` | MediaPipe Tasks adapter, model categories, source-frame coordinates. |
| `modules/vision/marsdog_vision_interaction/providers/hand_backends/rknn.py` | RKNN ROI projection, relative z scaling, geometry-based ROI continuity. |
| `modules/vision/marsdog_vision_interaction/messages/visual_event_types.py` | Public action-to-emotion/special-event lookup. |
| `modules/vision/marsdog_vision_interaction/messages/visual_event_derivation.py` | Independent public pose and hand event derivation. |
| `modules/vision/tests/test_gesture_pose.py` | Synthetic landmarks, smoothing boundaries, public projection, temporal reset regressions. |
| `modules/vision/tests/test_visual_contract.py` | Public action names/categories/labels and event behavior. |
| `modules/vision/tests/test_hand_backends.py`, `test_hand_model_integration.py` | Backend coordinate and provider conversion tests. |
| `modules/vision/docs/ROS2_CONTRACT.md`, `TEST_ENGINEER_GUIDE.md`, `rknn-hand-models.md` | Published taxonomy, diagnostic fields, acceptance limitations. |

- `HandLandmark` has x/y/z, visibility, and presence (`gesture_pose_engine.py:159`). `HandFeatures` already provides five finger joint straightness values and extension states (`:270`); `_hand_finger_straightness` uses minimum PIP/DIP 3D angle (`:698`). These support continuous flexion rather than a one-frame open/closed decision.
- `BehaviorEngine` retains 30 timestamped observations, derives temporal features, scores and smooths per track (`:5026`, `:5065`, `:5074`). New hand-local temporal metrics fit this architecture; a new model or module is unnecessary.
- `RuleActionClassifier.classify` initializes scores from every `ActionName`, invokes pose, temporal, and hand rules, then resolves conflicts (`:2722`). A new action must also join `ACTION_GROUPS`, `ACTION_TRIGGER_PRIORITIES`, and `_WITHIN_TIER_PRIORITY` (`:1924`, `:1954`, `:1992`). There are currently 27 enum actions, so documentation becomes 28.
- `ActionSmoother` has explicit action-specific policies (`:4833`). Existing dynamic waving uses a five-update window, >=3 supporting scores of >=0.55 to enter, retained at exactly 2/5 and released below 2/5 (`:4635`, `:4851`). Frame-count windows count actual classifier calls, not camera FPS or ROS snapshot refreshes.
- `PoseActionClassifier` picks the first ranked pose and independently the first ranked hand action (`pose_action.py:253`). Public key can be `beckoning`, label `招手`, category `pose`; add it to `_POSE_ACTIONS` and `_ACTION_LABEL`, not `_HAND_ACTIONS`. Stable and raw diagnostic arrays are already generated generically (`:421`).

### Orientation is the main missing evidence

- `_hand_palm_facing_score` computes `abs(normal.z)/|normal|` from wrist, index MCP and pinky MCP (`gesture_pose_engine.py:712`). Its absolute value destroys palm/back polarity. A high value establishes a palm plane facing the image plane, not a palm facing the subject. Neither this score nor `1-score` implements the requirement.
- Source coordinates use normalized x by image width, y by height, and model z in normalized image-width scale (`hand_backends/base.py:29`). RKNN explicitly preserves the MediaPipe normalize_z=0.4 mapping (`rknn.py:432`). They are model-relative coordinates, not camera-calibrated metric 3D. Do not subtract hand z from body/face z to establish subject depth.
- RKNN COCO pose supplies `z=None`; `PoseLandmark` explicitly prohibits interpreting unavailable depth as zero (`gesture_pose_engine.py:146`). A signed 3D hand-to-body vector cannot be reconstructed from those body points.
- Existing forward bend logic estimates reliable left/right facing from nose beyond the ear interval; an ambiguous frontal face yields no signed image-facing direction (`:550`). This helper can inspire a conservative profile gate but is not a complete frontal/back-facing classifier.
- `_behavior_hands` assigns left/right solely from string handedness (`vision_observation.py:1636`). `HandResult` has handedness confidence, but `as_observation` and engine inputs do not carry it (`base.py:75`, `gesture_pose_engine.py:4979`). Backend tracking deliberately does not trust handedness as identity because mirrored streams and transient category flips exist (`rknn.py:724`). A signed palm normal cannot blindly multiply by whichever current slot is called left/right.
- Current provider only feeds hand landmarks when a current active body pose exists (`vision_observation.py:1321`); its comments describe single-target hand use (`:1311`). There is no general hand-to-person association at this point. A new rule should verify each candidate wrist against the active body's visible wrists locally and abstain on crossed/ambiguous assignments, rather than redesigning global hand association.

### Conservative technical recommendation

1. Add an observable `BECKONING` dynamic action and public `beckoning` pose field. Use P3 with an explicit within-tier position before generic raised/waving poses; preserve existing P0-P2 precedence. P3 currently yields a debug `positive_candidate` state hint; that is diagnostic, not an Emotion event. Record this choice in design.
2. Compute palm-local flexion from multiple non-thumb fingers. Start with a coherent multi-finger pattern (e.g. at least three of index/middle/ring/pinky), clear PIP/DIP angular excursion, and corroborating tip travel relative to MCP/palm. This first version should exclude isolated index beckoning/pointing. Exact geometric thresholds are design defaults, not measured model accuracy.
3. Build separate left and right contiguous temporal segments. Require at least two complete flex-and-reopen cycles on the same valid hand within a bounded monotonic-time interval, meaningful excursion, and several intermediate observations. Count complete cycles, not arbitrary direction flips or a sum assembled across hands. Subtract palm/wrist translation or use joint angles; whole-hand XY motion alone does not establish curling.
4. Gate the action on actual palm-toward-subject evidence. Preserve the existing unsigned palm score for other actions; introduce signed palm normal evidence separately. Establish anatomical side by an unambiguous current body-wrist association and a documented model/display coordinate convention. Compare the signed orientation with the reliably projected direction toward the person's upper body in supported oblique/profile geometry. Reject degenerate normals, edge-on ambiguity, inconsistent side identity, absent body anchors, and unverified orientations. For frontal palms whose direction lies predominantly in z, the implementation needs an explicitly justified front-facing-body/model-side convention; do not pretend the existing 2D profile helper establishes it. If reliable frontal evidence cannot be established, document that angle as unsupported rather than silently accepting hand open-close as beckoning.
5. Bound time gaps and maintain current evidence. Missing hand, hand-side jumps, stale observations, reversed timestamps, target change, or loss of body association must break cycle continuity. Prior completed cycles must expire while the hand holds still; otherwise a static fist after one historical gesture would remain positive indefinitely. Clear only this action's smoothing votes when its required source becomes invalid, following `ActionRecognizer` current-evidence clearing patterns (`gesture_pose_engine.py:4933`).
6. After cycle qualification, use a brief bounded recent-cycle score through the existing 3/5 dynamic smoothing policy. Define the time window, recent-cycle validity, score threshold, and release behavior explicitly. Ensure the completed gesture stays eligible long enough for three true classifier updates without allowing duplicate snapshots to manufacture new cycles. Neither a single curl nor one frame should become a stable public result.
7. Resolve conflicts from specific evidence: valid beckoning suppresses the generic raised/waving candidate on its originating hand and clears retained conflicting votes; static raising and normal wrist waving remain recognized without curl cycles. Stop remains higher precedence and must invalidate beckoning votes. Do not globally clear valid other-hand pointing/V/Stop evidence. Current raw scoring collapses per-hand scores into maxima (`:3486`), so source-side evidence must be retained locally for precise conflict decisions. If implementing only aggregate conflicts, explicitly document that narrower tradeoff and test bilateral cases.
8. Keep `beckoning` out of `_ACTION_EMOTION` and `_SPECIAL_ACTION_EVENTS` (`visual_event_types.py:23`). Existing field normalization uses string pose values without a fixed public action enum (`visual_event.py:59`, `:108`, `:131`). No ROS type/topic/schema change is needed. Event derivation still independently processes hand actions (`visual_event_derivation.py:33`): test a pure beckoning input has no derived action event, and explicitly valid coexisting actions preserve their established events. Generic presence or facial-expression events are independent.

### Validation and limitations

- Synthetic landmark sequences can establish: exact key/label/category; signed palm/back distinction under the documented convention; left/right symmetry; image translation/scale invariance; multiple coherent finger cycles; no activation on one curl, static open palm/fist, generic waving, noisy jitter, wrist-only motion, pointing, or cross-hand alternation; bounded stale-history release; missing/degenerate geometry; timestamp/track resets; conflict-history clearing; public/debug serialization; absence of new action events.
- Include real adapter-shaped RKNN/MediaPipe outputs and body-pose `z=None` in pure tests. HandResult remains float32 internally while public landmarks round to four decimals (`vision_observation.py:2620`); engine rules must consume `_behavior_landmarks`, not the rounded wire payload.
- Tests with only patched classifier scores cannot prove that the proposed landmark geometry recognizes beckoning. Use engine-to-adapter sequences and precise cycle-boundary fixtures, then separately exercise smoother boundary behavior.
- Pure tests cannot establish camera handedness calibration, model finger-depth accuracy while the palm faces inward, occlusion performance, recognition recall/false-positive rate, NPU cadence, or real robot reaction. A short real-person video replay across both hands, supported views, and negative actions is the future model acceptance evidence; unavailable hardware does not block the software change, and model acceptance must be reported separately.
- Planned gates: `python3 -B tools/dev.py check`, `python3 -B tools/dev.py test vision`, and `python3 -B tools/check_visual_contracts.py` per the GesturePose spec. No tests, hardware, ROS transport, or model inference were run during this research. Preserve skip reasons as limits, not passes.

### Related specs and source records

- `.trellis/spec/backend/vision-gesture-pose.md`: raw versus stable output, taxonomy completeness, conflicts, independently selected pose/hand output, required docs and checks. Its static-posture 6/10 policy applies to bend/squat; a new dynamic beckoning action should explicitly document its dynamic policy rather than inherit static attention rules.
- `.trellis/spec/backend/vision-owner-posture-event.md`: owner posture event consumes only `bend_over`/`squat_down`; beckoning does not join that predicate.
- `README.md`, `CONTRIBUTING.md`, `docs/development/WORKFLOW.md`: owner-module implementation, frozen ROS/cancellation/boundary semantics, independent environments, isolated tests.
- `docs/migration/P4_VISION.md`, `docs/migration/VISION_UPSTREAM_SYNC_2026-10-08.md`: development stays in the platform module; preserve import provenance and existing thresholds outside the new action.
- `.trellis/workflow.md`: research artifact belongs under the supplied task path; planning remains separate from implementation.
- External references: none consulted. Checked-in `rknn-hand-models.md` documents 192-square palm detector, 224-square landmark graph, current FP16 models and explicit CPU/MediaPipe rollback; this task does not require model/runtime changes.

## Caveats / Not Found

- No dedicated beckoning enum, public mapping, cycle feature, signed palm-to-subject gate, or beckoning accuracy dataset was found.
- No camera-calibrated common body/hand 3D space or guaranteed model handedness calibration is available to the engine.
- The current hand contract omits image aspect ratio from standalone engine input. Normalized x/y/z geometry already follows existing conventions; avoid broad geometry correction in this feature and state angle assumptions honestly.
- Whole-hand inward/reaching motion, palm-up invitation gestures, and isolated index-finger beckoning are different observable patterns and should remain outside this explicitly multi-finger inward-curl definition unless the PRD broadens it.

### Implemented disposition (2026-10-14)

- The initial geometry investigation did not justify a signed palm direction for profile/side views. Implementation therefore supports only a conservative frontal face/body branch and abstains for side/profile views. It requires nose, both eyes, both ears, and both shoulders at visibility/presence `>= 0.7`, applies face-layout and semantic left/right ordering gates, compensates image mirroring from shoulder order, and signs the palm normal with its camera-z component. The index-to-pinky MCP horizontal span must be at least `0.05 × shoulder_width` to reject near-edge-on palm projections.
- The hand must uniquely match a visible wrist on the current active target. Per cycle, the same at least three non-thumb fingers cross from `>=145°` to `<=125°` and reopen; fingertip distance must contract by at least `0.35 × palm_width`, reach no more than `1.35 × palm_width` while flexed, and return within `0.15 × palm_width` of its extended baseline. Two cycles must complete within `1.8 s`, with gaps no longer than `0.35 s`; completed evidence expires after `0.55 s` and uses the dynamic 3-of-5 smoother.
- Generic raised/waving scores are aggregated across hands, so their raw and retained history is not cleared on beckoning evidence; the P3 ranking makes stable beckoning win the public pose slot. Same-hand pointing evidence is handled source-aware, and unknown/other-hand history is retained. This preserves possible independent hand evidence.
- These are software geometry thresholds verified with synthetic landmarks. The task has no real-person video or camera-accuracy evidence; the supported-angle and recognition-accuracy limits remain explicit.
