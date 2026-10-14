# Implementation plan

## Implementation Status — 2026-10-14

- Implementation, independent review, and validation are complete; task remains `in_progress` pending the code commit and Trellis archive step.
- Confirmed semantics: come-hither beckoning, labeled `[12, 20)` seconds. The original video is not committed. The 120-sample fixture contains only COCO shoulder/elbow/wrist and detected 21-point hand landmarks.
- Final RKNN result: `/tmp/wave_hand_final_rknn.json`; 457/457 person and hand detections, 0 backend errors, RGA preprocessing, and 15 stable `pose_action=beckoning` samples from 18.153173 to 19.287746 seconds.
- Focused tests: `test_gesture_pose.py` 177 passed; fixture/replay-range tests 4 passed (181 combined).
- Vision suite: 668 collected, 665 passed, 0 failures/errors, and 3 explicitly skipped RGA parity smokes (`PASS_WITH_EXPLICIT_LIMITS`). `python3 tools/dev.py check` exited 0; visual contracts passed with 0 skips.

## 1. Curate the positive sample

- [x] Confirm the active gesture interval and expected positive semantics in `wave_hand.mp4`.
- [x] Create the fixture manifest with source SHA, interval, configured inference cadence, and production model fingerprints.
- [x] Keep the original MP4 out of Git and generate a compact trace from actual RKNN outputs, omitting face points and video pixels.

## 2. Change the rule engine

- [x] Update the rule so sequence evidence uses same-body-side wrist association and measurable finger phases without face/palm-orientation hard gates.
- [x] Bridge short unassociated observations only while consecutive valid same-side matches remain within the existing `0.35 s` bound; preserve cycle, same-finger, travel, window, grace, and track/reset constraints.
- [x] Preserve per-hand conflict attribution and other-hand stop/pointing precedence.

## 3. Add regression coverage

- [x] Add orientation/face ambiguity expectations and short-dropout versus over-gap coverage.
- [x] Retain negatives for straight-finger arm waving, static hand, one cycle, jitter, no travel, different fingers, reset, pointing, and stop precedence.
- [x] Add deterministic trace-fixture and replay-range tests without model assets or hardware.

## 4. Make RKNN replay reproducible

- Add or extend an offline Vision tool to sample the clip without camera/ROS access, call the configured production RKNN pose and hand providers, feed observations through the real behavior engine, and write a JSON result.
- [x] Include backend readiness, model fingerprints, preprocessing mode, sample/detection counts, backend errors, raw scores, and `pose_action` timestamps in the report.
- [x] Replay the original on RK3588 after the rule change; stable beckoning appears in `[12, 20)`. Keep performance separate from functional acceptance.

## 5. Verify and report

- [x] Run focused `test_gesture_pose.py`, the full Vision suite, `python3 tools/dev.py check`, and `python3 tools/check_visual_contracts.py`.
- [x] Run the RKNN replay separately from pure tests and record its acceptance; report the three Vision RGA parity skips explicitly.
- [x] Review frozen identifiers/contracts, fixture privacy/provenance, and unrelated changes; independent Trellis review passed.

## Expected files

- `modules/vision/marsdog_vision_interaction/providers/gesture_pose_engine.py`
- `modules/vision/tests/test_gesture_pose.py`
- `modules/vision/tests/fixtures/beckoning/` (manifest, compact trace, and optional face-obscured video)
- `modules/vision/tools/replay_beckoning.py` (only if no existing replay path can provide the required report)
- `modules/vision/docs/ROS2_CONTRACT.md` only if clarifying the existing recognized-pose behavior is needed; no interface/schema change
