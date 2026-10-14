# RKNN diagnostics for `wave_hand.mp4`

## Replayed input

- Source: `/home/marsdog/marsdog_ws/src/MarsDogVisionInteraction/data/datasets/test/videos/simu/wave_hand.mp4` (about 4.7 MiB, 30.5 seconds, 914 frames).
- Source SHA256: `116ff624392c9f7ba448632989de63675d87361c73b58488daf2cc1cce2c76d1`.
- Inference sampled every other frame, matching the production cadence of about 15 samples/second.
- Pose: `models/vision/yolov8n-pose-fp16.rknn` (COCO-17 input mapped by the existing adapter).
- Hands: `models/vision/hand_detector_fp16.rknn` and `models/vision/hand_landmarks_detector_fp16.rknn`, using the existing RGA preprocessing helper.
- Model SHA256: pose `74e0a714e3565c491b724787f7419b343d4e1451e56a8103c5b524c482fc1ce2`; hand detector `588b2b3749a864766de23caccd12b979305158dad8ea836098529c3f1874c373`; hand landmarks `9c973f44a100ebdd9aacbe54e7495fe046b2e94fe900f296d3c7a50189a0e7c4`.
- Replay used the actual RKNN runtime on the local RK3588 board. Runtime and driver were available; both model providers reported ready.

## Result before the strategy change

- 457 sampled frames; each sample had a detected person and at least one detected hand; no fatal inference errors.
- Raw `beckoning` score was zero for all samples and no stable `pose_action=beckoning` was produced.
- In the active interval around 14–20 seconds, the body-right hand was associated 57 times: 25 open, 24 closed, and 8 neutral observations. Palm-orientation geometry passed only 6 times; rejects included 38 polarity failures, 5 frontal-face geometry failures, 6 narrow palm spans, and 2 degenerate normals. The hand was unassigned in 33 observations.
- The full sampled replay took about 42.735 seconds for 30.5 seconds of video (about 0.71× source duration). This is functional evidence only, not a real-time performance result.
- Earlier MediaPipe CPU replay also returned no beckoning score, so the failure was not specific to the RKNN backend.

The initial reports were temporary diagnostics. Final post-change acceptance is recorded below and in the fixture manifest.

## Existing code and contract findings

- The rule and temporal state live in `modules/vision/marsdog_vision_interaction/providers/gesture_pose_engine.py`; synthetic beckoning behavior tests are in `modules/vision/tests/test_gesture_pose.py`.
- The currently frozen public projection is `pose_action=beckoning` / label `招手（示意过来）`. `modules/vision/docs/ROS2_CONTRACT.md` defines no ROS visual event for this action.
- The current policy requires two same-hand, same-finger open/curl/reopen cycles with fingertip travel inside 1.8 seconds, a maximum 0.35-second observation gap, and a 0.55-second completion grace. Do not silently weaken these independent motion checks while removing the camera-orientation hard gate.
- `modules/vision/.gitignore` excludes all of `data/*` and documents that real face samples are not committed. Keep the raw clip local; any checked-in visual fixture must be face-obscured, with a compact non-image landmark trace for deterministic pure regression.

## Implementation guidance

Use the production provider and behavior-engine paths for the RKNN replay; do not add a camera, ROS transport, fallback detector, or alternate model. Keep the pure landmark regression distinct from the hardware/model-dependent RKNN report. A missing model or runtime is unavailable integration evidence, not a passing test.

## Final result after the strategy change

- The gesture is come-hither beckoning, labeled `[12, 20)` seconds. It is not a straight-finger lateral arm wave.
- Final production RKNN/RGA replay report: `/tmp/wave_hand_final_rknn.json`; 457 sampled frames, 457 person detections, 457 hand detections, and zero backend errors. Stable `pose_action=beckoning` occurred at 15 discrete sample timestamps from 18.153173 through 19.287746 seconds; this does not claim continuous-frame coverage.
- The deterministic fixture has 120 samples and contains pose slots 11–16 plus detected 21-point hands only. It contains no face landmarks or image pixels. Its input/model fingerprints match the final replay.
- Verification after final CLI-range/spec/test review: Vision suite 668 collected, 665 passed, 0 failures/errors, 3 explicit RGA parity skips (`PASS_WITH_EXPLICIT_LIMITS`); focused `test_gesture_pose.py` 177 passed; fixture/replay-range tests 4 passed (181 focused combined); `python3 tools/dev.py check` exit 0; visual contracts PASS with 0 skips. Python AST and `git diff --check` pass; Vision has no separately configured mypy/pyright check.
