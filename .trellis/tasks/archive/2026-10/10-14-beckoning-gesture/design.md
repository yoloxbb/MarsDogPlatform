# Design: Beckoning Gesture Recognition

## Boundary and public contract

Implement the recognizer inside the existing Vision GesturePose pipeline. The internal action is `ActionName.BECKONING`; the public projection is `pose_action=beckoning`, `pose_action_label=招手（示意过来）`, category `pose`, and the existing GesturePose diagnostics. Keep it out of `hand_action` and out of visual-event, Emotion, BehaviorTree, and Action mappings. Do not change ROS types, endpoints, schema versions, model assets, or configuration.

Hand observations remain scoped to the current `active_target` and its existing per-track `BehaviorEngine`. Do not add hand-to-person association for other `human_candidates`. Continue selecting one primary pose and one independent hand action using the existing adapter contract.

## Recognition flow

1. Reuse the existing 21-point hand landmarks and per-target frame history. Keep all beckoning-specific motion state scoped to the target and hand side; never combine cycles from the left and right hands.
2. Add a hand-local curl feature from the non-thumb fingers. A qualifying observation needs at least three of the index, middle, ring, and little fingers to show meaningful flexion relative to their own extended baseline, supported by fingertip movement relative to the palm. Rigid wrist/arm translation and wrist waving alone do not count as curl evidence. Keep thresholds explicit in the engine and document them as synthetic geometry thresholds, not measured accuracy claims.
3. Maintain a bounded monotonic-time segment per hand. A segment qualifies only after at least two complete flex-and-reopen cycles by the same hand, with intermediate observations and bounded frame/time gaps. Count completed cycles rather than arbitrary direction flips. Expire old cycles while the hand is still, and break continuity on missing/invalid landmarks, ambiguous side assignment, target reset, excessive time gaps, or non-monotonic timestamps.
4. Require independent evidence that the palm is directed toward the subject. Do not reuse the existing unsigned `palm_facing_score`: it removes normal polarity and cannot distinguish palm from hand back. The implementation supports only frontal face/body geometry with reliable semantic left/right ordering across both eyes, ears, and shoulders; it compensates mirrored image coordinates with shoulder ordering and signs the palm normal by its camera-z component. Require the index/pinky MCP horizontal span to be at least 0.05 shoulder widths. Side/profile views lack reliable mirror polarity in current inputs and are unsupported. Reject degenerate normals, edge-on views, uncertain body-wrist assignment, and any orientation that cannot be signed from available observations. Do not compare hand z with body z; those coordinates are not a calibrated shared depth space.
5. Emit a raw `BECKONING` score only while recent cycle evidence and the signed palm gate are both valid. A completed sequence must remain eligible for enough classifier updates to pass the existing dynamic 3-of-5 smoother, but must not be replayed from duplicate snapshots as new cycles. Invalid required source evidence clears only beckoning's retained votes, following the current-evidence invalidation pattern.

## Priority and conflicts

Add `BECKONING` to `ACTION_GROUPS`, `ACTION_TRIGGER_PRIORITIES`, and `_WITHIN_TIER_PRIORITY`. Treat it as dynamic P3 evidence, ahead of generic `ARMS_RAISED`/`WAVING` in stable pose projection when its full gesture is confirmed, while preserving all P0-P2 precedence and Stop's higher precedence. Generic raised/waving scores aggregate both hands, so retain their raw and smoother histories rather than clearing possible other-hand evidence; the P3 within-tier order keeps the public pose distinct. Do not globally clear an independent valid hand action or erase unrelated action history. Track originating hand evidence for pointing conflict decisions.

Pointing is a negative/conflict case: a static extended index must not create a beckoning cycle, and valid beckoning evidence must not leak a false `finger_pointing` pose from the same hand. Suppress the same-side pointing raw score and clear retained pointing votes only when their source is attributable to the beckoning hand; preserve independently confirmed pointing/Stop/other hand-action behavior from another side or unknown source. No new event mapping is added, and existing presence/facial events continue to be derived independently.

## Data flow and documentation

`RuleActionClassifier` computes raw evidence, `ActionSmoother` establishes stable recognition, and `PoseActionClassifier` maps the stable action to the existing public fields. Keep raw debug scores diagnostic-only and expose the exact stable name through the existing diagnostics. Update the action taxonomy count to 28 and add GP-028 to `modules/vision/docs/ROS2_CONTRACT.md` and `modules/vision/docs/TEST_ENGINEER_GUIDE.md`. Do not modify visual-event v1 fixtures or the compatibility baseline.

## Verification approach

Use synthetic landmark sequences through the real engine-to-adapter path. Cover both hands, signed palm versus back-of-hand, at least two coherent cycles, cycle expiry, missing/ambiguous orientation, unsupported geometry, wrist translation/waving, raised arm, static pointing, one curl, cross-hand alternation, jitter, side flips, stale time gaps, target reset, priority/conflict history, public fields/diagnostics, and absence of derived beckoning events. Include adapter-shaped MediaPipe and RKNN observations and body landmarks with `z=None`; tests must not claim calibrated physical accuracy.

The key acceptance limit is reliable polarity of the palm relative to the subject. Existing source inspection found no calibrated common body/hand 3D space and no guarantee that all view angles provide signed body orientation. The first implementation must state which geometry it can support and abstain elsewhere. Real-person video and device performance remain separate acceptance evidence.
