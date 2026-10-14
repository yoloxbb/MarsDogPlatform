# Design: robust beckoning evidence with a real positive fixture

## Confirmed failure before the fix

The original `_beckoning_evidence` required every hand sample to pass frontal-face and signed-palm checks, so orientation ambiguity discarded many usable finger samples. Removing those unrelated orientation gates exposed the remaining root cause: the loop cleared its candidate segment immediately on every unassociated sample, even when the next valid same-side wrist association arrived within the existing `0.35 s` maximum gap. The clip's right hand has short RKNN assignment gaps during an otherwise valid repeated curl sequence.

The same hard orientation validity had also been used by `PoseActionClassifier` to clear smoothed beckoning votes. Both the sequence source and smoother source checks now use same-side wrist association and measurable finger evidence.

## Proposed rule

1. Keep `_beckoning_hand_assignments` as the source of identity: associate a detected hand with a body-side wrist and reject ambiguous wrist assignments.
2. Treat the finger motion sequence as the primary gesture evidence. Continue requiring two cycles on the same body-side hand, at least three shared fingers, the existing fingertip-travel threshold, the existing sequence window/max observation gap, and the current completion grace period. Skip an unassociated frame, then enforce the same `0.35 s` maximum between consecutive valid same-side associations; a missing current hand still cannot itself emit a candidate.
3. Do not require a signed palm normal or frontal-face geometry for a frame to participate in the cycle sequence or to preserve smoothed votes. These measurements are unreliable in the supplied views and are not needed to distinguish repeated finger curls from a straight-finger arm wave.
4. Preserve current stable action thresholds, hand-action conflict handling, track/reset behavior, and action taxonomy. A pointing or stop gesture on the other hand keeps its existing precedence.
5. Keep the output as the existing Vision `beckoning` pose action. Do not add an event or alter a ROS interface.

This is a narrow strategy change: body-wrist association and finger-phase evidence remain hard requirements; camera-facing palm direction and face frontalness cease to be hard gates.

## Regression fixture

- Keep the original source MP4 at its supplied local path; it is outside the main repository and contains a visible person.
- Add a face-obscured copy only if the video itself is needed as a checked-in fixture. Place it under `modules/vision/tests/fixtures/beckoning/`, outside ignored runtime `data/`, and document source provenance, obscuring, and the labeled active interval in a manifest.
- Record a compact deterministic landmark trace extracted from the actual RKNN replay for the confirmed `[12, 20)` second active interval. Include only shoulder/elbow/wrist points needed for side association and the 21 hand landmarks; omit image pixels and face landmarks. Unit tests replay this trace through the real rule engine without model assets or NPU access.
- Add or extend an offline replay entry point that accepts a video path and configured production RKNN models, samples with the same frame stride, and emits a machine-readable report. It must not open ROS transports or cameras. Run it against the supplied original in the local board environment and, where the obscured fixture preserves inference, against the checked-in fixture as a regression check.

The pure landmark regression and the RKNN model replay are reported separately. Missing RKNN runtime/model assets is an unavailable integration result, not a successful pass.

## Failure and negative behavior

Retain and exercise the current negatives for missing/ambiguous hands, short observation gaps, changed track, missing/shared-finger evidence, insufficient travel, static fingers, and precedence with pointing/stop. Update the old polarity-only rejection expectation: a valid two-cycle sequence remains eligible when the palm normal is reversed, ambiguous, or intermittently unavailable. Add a straight-finger arm-wave sequence as the semantic negative.

## Acceptance output

The unit trace must yield a raw beckoning score at or above the existing action threshold and a stable `pose_action=beckoning` during the labeled interval. The offline RKNN report must show at least one stable result in that interval, no backend/runtime errors, and include the model paths/fingerprints, backend/preprocessing mode, sample counts, per-sample raw scores and recognized action timestamps. No positive result is required outside the labeled interval.

## Compatibility and risks

- The public action name and message schema remain frozen.
- Removing orientation gating can increase false positives if finger phases are noisy. Existing shared-finger/travel/timing constraints and new straight-finger/static negatives limit that risk.
- The source clip will not be copied unmodified into the public repository. A face-obscured video fixture and non-image landmark trace preserve regression value without publishing the visible face.
- The earlier RKNN replay took about 42.7 seconds for 30.5 seconds of source video at the tested cadence. This software acceptance does not claim real-time performance.

## Verified implementation result

- The 12–20 second clip segment is visually a come-hither gesture with repeated finger flexion, not a straight-finger lateral arm wave.
- With the gap bridge, the final actual RKNN replay produced 15 stable `pose_action=beckoning` sample points from 18.153173 to 19.287746 seconds. These are discrete stride-2 samples, not an assertion that every inference frame in that time span was positive.
