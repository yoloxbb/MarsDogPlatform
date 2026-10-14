# Add a real RKNN beckoning positive and tune recognition

## Goal

Make the provided real beckoning gesture reliably produce the existing Vision `beckoning` pose action, and keep it as a repeatable positive regression case.

## Background

The source clip is `/home/marsdog/marsdog_ws/src/MarsDogVisionInteraction/data/datasets/test/videos/simu/wave_hand.mp4`. It depicts a come-hither beckoning gesture: the same hand repeatedly curls and reopens its fingers. The confirmed positive interval is `[12, 20)` seconds. The initial RKNN replay detected a person and hands throughout but produced no beckoning score. Trace analysis found that strict face/palm-orientation gates rejected usable cycles and, after those gates were removed, short unassociated hand observations still cleared the pending cycle despite valid same-side matches being less than `0.35 s` apart.

## In Scope

- Treat the supplied clip as a labeled positive, with the active interval recorded in a fixture manifest.
- Tune only the Vision gesture-pose rule so reliable same-hand repeated finger-curl evidence is not discarded by intermittent or unavailable face/palm-orientation geometry.
- Preserve wrist-to-body-side association, repeated same-finger open/curl/reopen evidence, meaningful fingertip travel, timing bounds, and current conflict handling with other-hand gestures.
- Add deterministic regression coverage from the real sample and retain a separate RKNN replay acceptance result using the production models.
- Keep the established `beckoning` / `pose_action=beckoning` identifiers and current ROS contract unchanged; this action does not add a ROS visual event.

## Out of Scope

- Model retraining, quantization, runtime or model replacement, and camera/driver changes.
- Adding a ROS topic, event, or changing any public interface.
- Broad changes to other pose or hand-action policies.

## Constraints and Key Decisions

- The checked-in repository is public, and Vision excludes local runtime data and real face samples from Git. Keep the original MP4 at its supplied local path; if a video fixture is needed in the repository, use a face-obscured copy under `modules/vision/tests/fixtures/beckoning/` and record its provenance. The deterministic test fixture should contain only the minimum landmark trace needed to replay the classifier.
- Palm polarity and frontal-face geometry may provide supporting evidence when reliable, but transient ambiguity must not erase a valid finger-motion sequence.
- An arm wave with straight fingers, a static open hand, one curl cycle, unrelated fingers, or finger motion without meaningful tip travel remains negative.
- Preserve the current module and ROS compatibility boundaries.

## Acceptance Criteria

- [x] The supplied positive produces raw `beckoning` evidence and stable `pose_action=beckoning` results during its labeled active interval when replayed through the existing RKNN pose/hand models.
- [x] The sample has deterministic regression coverage that runs without model files or NPU hardware.
- [x] Existing negative cases remain negative; straight-finger arm-wave and orientation/face ambiguity positives are covered.
- [x] Existing wrist association, track reset, pointing, stop-gesture precedence, timing, and shared action-taxonomy tests continue to pass.
- [x] The RKNN replay report identifies the model/backend and reports detections, candidate scores, recognized-action timestamps, and errors; pure tests and hardware replay are reported separately.
- [x] `python3 tools/dev.py check`, the Vision test suite, and required Vision contract checks completed; three RGA parity cases are recorded as skips, not passes.

## Risks and Deferred Questions

- Relaxing palm-orientation gating can increase false positives. The repeated same-hand curl, shared-finger, travel, and timing requirements are retained as the primary evidence, with explicit straight-finger and static-hand negatives.
- The checked-in trace manifest records the confirmed `[12, 20)` interval, source/model fingerprints, and privacy-minimized landmark contents.
- No ROS event is defined for beckoning in the current contract, so this acceptance is the recognized pose action only.

## Planning Artifacts

- `design.md` describes the proposed rule and fixture design.
- `implement.md` lists implementation and verification steps.
