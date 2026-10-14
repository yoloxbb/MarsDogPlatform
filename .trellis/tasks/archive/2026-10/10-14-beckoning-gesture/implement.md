# Implementation Plan

## 1. Extend GesturePose evidence

- Read the GesturePose spec, PRD, design, and research evidence before editing.
- Inspect the current hand landmark projection and invalid-source clearing patterns in the engine and adapter. Use a conservative frontal-only signed palm polarity gate with semantic face/body ordering and a unique active-target wrist association; side/profile views abstain because mirror polarity is not reliable. Do not assume body z is available.
- Add the internal `BECKONING` action and its group, P3 trigger priority, and within-tier order. Keep existing action priorities unchanged.
- Add per-hand curl-cycle evidence from multiple non-thumb fingers, with bounded monotonic time, same-hand continuity, complete flex-and-reopen counting, expiry, and fail-closed handling for missing or ambiguous evidence.
- Add the signed palm-toward-subject gate only for supported, demonstrable geometry. Keep the existing unsigned palm feature behavior unchanged for existing actions.
- Feed only qualified recent beckoning evidence into the existing dynamic 3-of-5 smoothing policy. Stable P3 pose ordering puts confirmed beckoning before aggregated raised/waving scores without clearing possible other-hand votes. Suppress same-side pointing and clear pointing history only when its originating hand is attributable; preserve Stop, higher priorities, and unrelated hand actions.

## 2. Project the pose-only contract

- Map stable `BECKONING` to `pose_action=beckoning`, `pose_action_label=招手（示意过来）`, and category `pose`; do not add it to `hand_action`.
- Expose the exact action name using existing GesturePose diagnostics.
- Leave `visual_event_types.py`, ROS interfaces, Emotion, BehaviorTree, and Action routes unchanged. Verify a pure beckoning snapshot derives no new event.
- Document action GP-028, dynamic smoothing, supported geometry, no-event behavior, and acceptance limits; update the action count from 27 to 28.

## 3. Regression coverage

- Add engine-level synthetic sequence tests for both hands, multi-finger cycles, frontal palm polarity under mirrored inputs, one-cycle/static/wave/raised/pointing negatives, hand-side isolation, edge-on threshold (0.05 of shoulder width), unsupported side/profile and missing geometry, stale gaps, expiry, and reset behavior.
- Add conflict and smoother boundary coverage, including preservation of P0-P2/Stop and unrelated valid hand actions.
- Add public field, label, category, diagnostic, and no-event assertions through the existing adapter/event derivation path.
- Ensure tests never connect to hardware or production ROS. Preserve distinct ROS transport reports and do not count skipped transport checks as passes.

## 4. Validation and review

- Run `python3 -B tools/dev.py check`.
- Run `python3 -B tools/dev.py test vision` and review the affected GesturePose and visual contract test results.
- Run `python3 -B tools/check_visual_contracts.py` and confirm the visual-event v1 baseline remains unchanged.
- Review changed files for preserved ROS names/types/endpoints, target lifecycle/reset behavior, cancellation and demand semantics, taxonomy priority, and absence of event or robot-behavior changes.
- Report any unsupported view geometry or absent real-device evidence explicitly; synthetic passing tests do not establish camera/model accuracy.

## Rollback points

- The feature can be reverted by removing the `BECKONING` classifier evidence, its public pose mapping, its action-table entries, tests, and GP-028 documentation. Existing action thresholds and public event contracts must not need rollback changes.
- If signed palm polarity cannot be established for any supported geometry using existing observations, stop before weakening the ambiguity gate or adding a model/calibration/configuration change. Keep implementation within the agreed pose-only scope and report the blocker for a product decision.
