# Beckoning detection evidence

## Current Vision pipeline

- `modules/vision/marsdog_vision_interaction/providers/gesture_pose_engine.py` owns `ActionName`, score calculation, temporal history, priority ordering, and action smoothing. `BehaviorEngine` keeps up to 30 source-frame samples per target; `RuleActionClassifier` scores each action and `ActionSmoother` publishes stable actions.
- The existing `WAVING` raw rule requires a wrist above a shoulder, wrist motion energy, and direction reversal; it also favors open hands and discounts whole-arm motion (`gesture_pose_engine.py:2890-2929`). `WAVING` and `ARMS_RAISED` both use P3 and collapse to the public `arm_raise_wave` value.
- Dynamic actions such as `WAVING`, `LARGE_ARM_SWING`, and `JUMPING` use the existing 3-of-5 temporal smoother (`gesture_pose_engine.py:4638-4728`). The action tables require each new `ActionName` to have a group, trigger priority, and within-tier priority.

## Hand evidence available

- Both configured Hand backends normalize each hand to 21 landmarks containing x/y/z and handedness (`providers/hand_backends/base.py:35-72`). `vision_observation.py` assigns backend outputs to left/right slots by handedness before passing them to the per-target engine (`vision_observation.py:1640-1650`).
- Existing single-frame features include finger joint straightness, extended-finger flags, openness, and a palm-plane score (`gesture_pose_engine.py:270-300, 699-779`). Temporal samples retain the hand landmark sequence, so repeated flex/extend cycles can be measured without a model or ROS change.
- The current palm score is `abs(normal.z) / magnitude` (`gesture_pose_engine.py:712-732`), which reports camera-axis alignment but discards which way the palm faces. It cannot alone prove that the palm is directed toward the subject. A side-aware signed orientation feature and a conservative ambiguity policy are needed for the user's stated palm-facing-self criterion.

## Public output and compatibility

- `PoseActionClassifier` maps selected engine actions to the existing `pose_action`/`pose_action_label` fields; `get_action_category()` reports mapped pose values as category `pose` (`providers/pose_action.py:33-84, 247-255`). Vision snapshots carry these fields in the existing schema.
- Visual event derivation uses explicit maps in `messages/visual_event_types.py:26-58`. A new action key not placed in either event map produces no event. The user's scope decision is to add only the pose key/label: no ROS event, Emotion mapping, BehaviorTree route, or Action effect.
- The visual-event v1 baseline and ROS types do not need to change. The action taxonomy and its no-event behavior should be documented in `modules/vision/docs/ROS2_CONTRACT.md` and `modules/vision/docs/TEST_ENGINEER_GUIDE.md`.

## Existing conventions and coverage

- `.trellis/spec/backend/vision-gesture-pose.md` is the active contract for keypoint action taxonomy, temporal smoothing, conflict handling, public mapping, debug output, and test coverage.
- Existing synthetic action sequences and public mapping tests live in `modules/vision/tests/test_gesture_pose.py` and `modules/vision/tests/test_visual_contract.py`. The engineer guide currently documents GP-001 through GP-027; beckoning should become GP-028 and increment the precise GesturePose action count from 27 to 28.
- Recent project conversation memory only confirms the already-read distinction between current WAVING and a distinct beckoning action. Recent posture work established that selected P0-P4 engine actions feed `pose_action`, while additional lower-tier recognized actions remain visible in debug output; preserve priority sorting and the one-pose/one-hand output behavior.

## Validation limits

- Synthetic landmarks can verify cycle recognition, left/right orientation handling, conflict rejection, smoothing, public key/label, and absence of event derivation. They do not establish camera/model accuracy on physical users, which remains an honest hardware/model acceptance limit.
- Do not change model assets, inference backends, sample cadence, ROS endpoints, or schema versions for this feature.
