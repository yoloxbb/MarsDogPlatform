# Add beckoning gesture recognition

## Goal

Recognize “come here” beckoning as a distinct visual pose action: the subject turns the palm toward themself and repeatedly curls the fingers inward. Vision must distinguish this from greeting-style waving, a static raised arm, and pointing.

## Background and Constraints

- The current temporal `WAVING` rule looks for a raised wrist and repeated wrist motion. `ARMS_RAISED` and `WAVING` both map to `pose_action=arm_raise_wave`, so the public pose field cannot distinguish them (`modules/vision/marsdog_vision_interaction/providers/pose_action.py:55-72`).
- Hand observations contain 21 x/y/z landmarks and handedness. Existing features include finger straightness/extension and a palm-plane score. That palm score uses the absolute camera-axis normal component, so it does not identify which way the palm faces (`modules/vision/marsdog_vision_interaction/providers/hand_backends/base.py:35-72`; `modules/vision/marsdog_vision_interaction/providers/gesture_pose_engine.py:712-779`).
- Current hand inference is not associated with every detected person. `vision_observation.py` sends hand landmarks to the current active target's action engine, matching the documented single-main-target hand-action boundary (`modules/vision/marsdog_vision_interaction/providers/vision_observation.py:1323-1333, 1635-1650`; `modules/vision/docs/ROS2_CONTRACT.md:66-71`).
- The user selected the existing current-`active_target` scope. Do not add hand-to-person association for all `human_candidates`.
- Public snapshots already carry `pose_action` and `pose_action_label`; GesturePose debug output carries exact recognized action names. Visual event derivation uses explicit maps, so a new action can remain pose-only (`modules/vision/marsdog_vision_interaction/messages/visual_event_types.py:26-58`).
- The user chose pose-only output: no dedicated ROS event, Emotion mapping, BehaviorTree route, or Action behavior. Preserve visual-event v1, ROS names/endpoints, and all existing action keys.

## Requirements

- Add a distinct `beckoning` action for a palm directed toward the subject together with repeated inward finger-curl cycles. One isolated curl is not a beckoning action.
- Use the existing per-track keypoint history and hand observations; do not require a new model/runtime or new configuration.
- Only produce positive beckoning evidence when palm direction and repeated finger motion are sufficiently clear. Ambiguous palm orientation, missing hand landmarks, or static hand poses must not be treated as beckoning.
- Keep beckoning distinct from `waving`, `arms_raised`, and `pointing` in exact GesturePose recognition and in public structured output.
- Publish the stable action through the existing `pose_action=beckoning` and `pose_action_label=招手（示意过来）` fields, and expose its exact name in existing GesturePose diagnostics.
- Do not add an event mapping for `beckoning`; `events[]`, Emotion, BehaviorTree, and Action behavior remain unchanged.
- Preserve current key meanings, per-target lifecycle, output priority rules, and the existing independent `hand_action` field.
- Apply the new classifier only to the current `active_target`, reusing the existing single-target hand pipeline.

## Acceptance Criteria

- A repeated inward finger-curl sequence with the palm directed toward the subject produces stable `beckoning` recognition and public `pose_action=beckoning`, `pose_action_label=招手（示意过来）`.
- A left-hand and a right-hand example both work when their handedness and orientation evidence are valid.
- Greeting-style wrist waving without repeated inward finger curls, a static raised arm, and static pointing do not produce `beckoning`.
- Missing or ambiguous hand/palm-direction evidence does not produce `beckoning`.
- During a confirmed beckoning sequence, `pose_action` remains distinct and no false pointing or legacy raised-arm/waving compatibility value masks it.
- The new key derives no ROS visual event. Existing event names and derivation results remain unchanged, and visual-event v1 fixtures/baseline remain untouched.
- Existing action priority, one-pose/one-hand output, target isolation, and action release behavior remain intact.

## Out of Scope

- A dedicated ROS visual event, Emotion mapping, BehaviorTree candidate, Action execution, or robot motion change.
- ROS endpoint/type/schema-version changes, model/runtime upgrades, new model assets, or configuration changes.
- Claims of real-camera, RKNN/NPU, or robot accuracy beyond available software evidence.

## Open Questions

None. The user selected pose-only output and current-`active_target` coverage. Classifier thresholds and conservative handling of uncertain geometry are implementation decisions constrained by the acceptance criteria.
