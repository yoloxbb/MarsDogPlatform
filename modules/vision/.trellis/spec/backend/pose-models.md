# Pose model formats and keypoint contracts

## 1. Scope / Trigger

Changes to pose model selection, RKNN decoding, pose/hand action inputs, public
human keypoints, target tracking, held-object wrist association, or pose debug
metrics. The same source frame can run through MediaPipe `.task` or YOLOv8 Pose
`.rknn`, selected by the configured model path.

## 2. Signatures

- `providers.pose_backends.create_pose_backend(model_path, *, rknn_config=None, runtime_library="", score_threshold=.30, nms_threshold=.45, max_num_poses=4)` constructs the RKNN adapter for a `.rknn` path; the observation Provider retains MediaPipe `.task` construction.
- `RKNNPoseBackend.process(frame_bgr) -> list[PoseResult]` accepts a selected-view BGR image. Each result has a normalized source-view `(x,y,w,h)` box, a person score, and a `(17,3)` COCO `(x,y,confidence)` array.
- `RKNNPoseBackend.close()` is idempotent; `fatal_error` reports an unrecoverable runtime/output failure.
- Public human, active-target and candidate dictionaries carry `keypoint_format` beside `keypoints`: `coco_17` or `mediapipe_33`.

## 3. Contracts

- Keep `pose_model_variant`/`pose_models` for launch-time selection. An explicit `pose_model` path takes precedence, then the selected variant path, then legacy `mediapipe_model`. Production selects the supplied RKNN model; `.task` Lite/Full remain explicit rollback paths. Select the runtime by suffix and never silently fall back from RKNN to CPU.
- The verified `yolov8n_pose_fp16` profile requires SHA-256 `74e0a714e3565c491b724787f7419b343d4e1451e56a8103c5b524c482fc1ce2`, RGB uint8 NHWC 640×640 input, runtime std `[255,255,255]` normalization, `inputs_pass_through=[0]`, and one finite `(1,56,8400)` output. The output is 4 center-box values, 1 person score, then 17 `(x,y,confidence)` triples. Validate the content before lazy RKNN import. A different export needs a new reviewed profile and board parity evidence.
- Preserve centered aspect-ratio letterboxing and exact inverse mapping for non-square, odd-size, and non-contiguous source frames. Filter person scores, apply NMS, cap at `max_num_poses`, and report boxes/points in normalized selected-view coordinates. Empty output means no current pose detection.
- RKNN public points use native COCO IDs 0–16; MediaPipe points use native IDs 0–32. Missing `keypoint_format` in legacy records means `mediapipe_33`; an unknown present format must not be guessed. COCO shoulders/hips are 5/6/11/12 and wrists are 9/10; MediaPipe shoulders/hips are 11/12/23/24 and wrists are 15/16.
- COCO public `presence` repeats the model's keypoint confidence for compatibility with consumers that take `min(confidence, presence)`; it is not a second independent model output. COCO `z` is null.
- Only the action-engine boundary maps COCO into a 33-slot MediaPipe-indexed tuple. Unavailable landmarks have zero visibility/presence. COCO pose `z` is `None`: 3D angle/depth evidence is unavailable, while 2D pose and independent hand evidence remain usable. Do not publish invented Z or assign COCO IDs directly to MediaPipe slots.
- Pose diagnostics and UI use 17 or 33 as the validity denominator for the active backend. Carry the format through `humans`, `human_candidates`, `active_target`, normalized visual events, stereo fusion and OSD skeleton connections.
- Stop the observation worker before releasing RKNN. Serialize inference/close, release partial initialization, latch fatal runtime/output errors, clear current pose detections and expose readiness failure. Face/hand processing can continue; no CPU pose fallback occurs.

## 4. Validation & Error Matrix

| Situation | Required behavior |
|---|---|
| `.task` Lite/Full selected | MediaPipe loads without RKNN dependency and emits `mediapipe_33` |
| Verified `.rknn` selected | RKNN runs and emits `coco_17` with 17 native IDs |
| Unknown suffix/profile or altered fingerprint | Explicit load error; no alternate backend |
| Missing runtime or failed init | Release any partial context and expose pose unavailable |
| Nonfinite/wrong-shaped output or inference exception | Release once, latch fatal state, emit no current pose |
| Empty or suppressed detections | Return an empty current list; preserve only the existing temporarily-lost tracking policy |
| Legacy record with no format | Interpret MediaPipe IDs for compatibility |
| Unknown present keypoint format | Avoid a guessed torso or wrist association |
| COCO pose reaches action engine | All action categories remain evaluable from available evidence; missing Z never acts as measured depth |

## 5. Good / Base / Bad Cases

Good: switch `pose_model_variant` to `rknn`, publish native COCO IDs plus format,
then translate only at the action-engine boundary and validate a board frame.
Base: switch to `lite` and retain MediaPipe numbering and VIDEO tracking.
Bad: put COCO wrist 9 into the MediaPipe wrist 15 slot only in the public JSON,
or fill all absent points with confidence 1.0 and Z 0.0. That silently corrupts
target and action decisions.

## 6. Tests Required

- Backend: fingerprint/profile and suffix rejection, partial-load cleanup,
  BGR→RGB letterbox, odd/non-contiguous geometry, output shape/nonfinite
  rejection, 17-point decoding, score filtering, NMS, and zero/one/multi-person
  result counts.
- Provider: both config paths, VIDEO/IMAGE MediaPipe rollback, keypoint format,
  33-slot internal mapping, missing-Z action fallback, quality denominator,
  fatal status, worker-before-close lifetime, and empty-result freshness.
- Public flow: `humans`→target manager→candidates/active target→visual-event
  normalization, COCO and MediaPipe torso centers/wrist association, stereo
  fusion, and OSD graph topology.
- Board smoke: run the exact artifact on a real person frame and inspect box,
  joint positions and timing. A zero input or cartoon validates the runtime
  plumbing, not real-camera accuracy or temporal gesture parity.

## 7. Wrong vs Correct

Wrong: `pose_depth_reach = (shoulder.z - wrist.z) / scale` after substituting
`0.0` for unavailable COCO depth.
Correct: keep `PoseLandmark.z=None` for COCO and skip depth-dependent evidence;
use the existing 2D/perspective-hand path where available.

Wrong: infer the public point format from an ID such as 15, which means a wrist
in MediaPipe and an ankle in COCO.
Correct: carry `keypoint_format` explicitly and select torso/wrist IDs from it.

## Scenario: Identity gate for formal pose and hand events

### 1. Scope / Trigger

Apply this contract when changing how `pose_action` or `hands[].hand_action`
becomes an item in `/perception/visual_event.events[]`.

### 2. Signatures

- `messages.face_identity.pose_event_identity_eligible(identity, identity_state, tracking_state) -> bool`
- `VisionInteractionNode._derive_events(observation, emotion_classification="") -> list[str]`

### 3. Contracts

- The pose-event gate is open for a tracked registered identity only when its
  state is `confirmed_known`.
- It is also open for a tracked stranger only when
  `identity == "unknown"` and `identity_state == "confirmed_unknown"`.
- `candidate_known`, `unknown_candidate`, `unverified`, unknown state/identity
  mismatches, and any state other than `tracking` remain gated.
- Keep established event names and the visual schema unchanged. The event
  snapshot carries `active_target.identity` and `identity_state`, so consumers
  can distinguish a stranger action even when its event name contains
  `MASTER`.
- Face-derived stranger events are independent and may coexist with the pose or
  hand event in one `events[]` list. Viewer gate evidence and the Dashboard
  display follow the same predicate.

### 4. Validation & Error Matrix

| Active target | Gate | Required behavior |
|---|---|---|
| Registered identity + `confirmed_known` + `tracking` | Open | Preserve current mapped pose/hand events |
| `unknown` + `confirmed_unknown` + `tracking` | Open | Emit mapped pose/hand events; retain any face-derived stranger event |
| Registered identity + `candidate_known` | Blocked | Do not emit a pose/hand event |
| `unknown` + `unknown_candidate` or `unverified` | Blocked | Do not emit a pose/hand event |
| Any identity + non-`tracking` state | Blocked | Do not emit a pose/hand event |

### 5. Good / Base / Bad Cases

- Good: a tracked `unknown/confirmed_unknown` target jumps; the snapshot can
  contain `EVT_VISION_STRANGER` and `EVT_VISION_MASTER_HAPPY`, with stranger
  identity evidence in `active_target`.
- Base: a tracked registered `confirmed_known` target keeps its existing event.
- Bad: an `unknown_candidate`, `unverified`, or non-tracking target emits a
  formal pose/hand event.

### 6. Tests Required

- Keep the existing runtime-safety gate assertions aligned with the policy:
  confirmed stranger emits the mapped event, while candidate and lost targets
  remain blocked.
- Preserve an assertion that a stranger face event and its pose/hand event can
  coexist in the same snapshot.

### 7. Wrong vs Correct

Wrong: gate pose events solely on membership in `ALLOWED_FACE_IDENTITIES`,
which silently suppresses every confirmed stranger action.

Correct: use the shared eligibility predicate for both the publisher and
Viewer; allow the two confirmed identity cases above and keep all other states
closed.


## Scenario: Timed face covering

### 1. Scope / Trigger

Applies to FACE_COVERING rule/evidence, per-person timing, current-target face
observation plumbing, and legacy hand-action publication. Occlusion must not
make real covering impossible, and five predicted points must not independently
prove the covering ended.

### 2. Signatures

- `FaceObservation(bbox, landmarks=(), confidence=0.0, track_id=-1)` carries
  current associated normalized face geometry internally; YuNet has five x/y
  pairs and one face score, not per-point occlusion confidence.
- `LandmarkFrame(..., face_observation=None, target_present=None)` adds optional
  face and current-target presence evidence; defaults preserve existing callers.
- `PoseActionClassifier.update(..., face_observation=None, target_present=None)`
  forwards the same evidence without changing the old `face_observed` contract.
- `FaceCoveringConfig(activation_s=3.0, exit_s=1.0, unknown_grace_s=0.5)` names
  the finite positive monotonic timing defaults.
- The engine exposes `face_covering_detector` diagnostics via the existing
  gesture-debug payload; private face coordinates are not formal visual fields.

### 3. Contracts

- Evaluate a coherent same-person body and a current plausible face region.
  A hidden or inconsistent nose can be replaced by current ear/head/shoulder
  geometry or a bounded same-person cache. A confident lone nose is not a
  reliable anchor unless it agrees with current head/shoulder structure.
  Never renew a cache merely because it was reused; invalidate on torso
  displacement or scale inconsistency.
- Evaluate both sides independently, using associated hand geometry or reliable
  same-side pose wrist/elbow evidence. Hand center alone must not veto covering
  when a palm edge and the same person's wrist both overlap the face area.
  A hand from another person, a close-up
  palm's pseudo-person, or only proximity to a nose is insufficient.
- Activate exact FACE_COVERING only after 3 s of supported covering. Unknown
  observations pause candidate dwell; explicit interruption resets it so short
  independent gestures cannot be joined together.
- Once active, independently confirm either both hands away or a current clear
  face plus both hands no longer covering for a continuous 1 s. Re-cover cancels
  pending exit. Missing hands, face predictions alone, and stale detections do
  not count as uncovered evidence. Switching exit routes cannot concatenate
  their timers.
- Unknown longer than 0.5 s clears as evidence loss, separately from observed
  action end. A confirmed absent target clears immediately. A missing pose by
  itself is unknown, not proof the person left. Long sampling gaps cannot provide
  supported duration; reset all caches/timers on restart or target change.
- Preserve generic policies for every other action. FACE_COVERING lifecycle
  owns the exact stable label; frame-count smoothing cannot shorten 3/1 timing.
- Keep `FACE_COVERING -> hands_covering_face -> EVT_VISION_MASTER_SAD`, current
  known/unknown identity gate, and the same legacy mapping for HANDS_ON_HEAD.
  Pose-supported exact FACE_COVERING must reach formal routing even if the
  independent hand detector supplies no current coordinates. Provider emits a
  coordinate-free hands row only when `face_covering_detector.active` and
  `hand_action == "hands_covering_face"`: empty handedness/landmarks, same legacy
  action. Do not generalize this to other gestures or invent landmark points.

### 4. Validation & Error Matrix

| Situation | Required behavior |
|---|---|
| Cover shorter than 3 s | No stable FACE_COVERING |
| Cover reaches 3 s with continuous supported observations | Activate |
| One hand detector misses but same-side pose arm is reliable | Retain bilateral evaluation |
| Unknown for <=0.5 s | Preserve state; pause onset; break exit continuity |
| Unknown beyond grace, including recovery without intervening timeout call | Clear/reset; reappearance starts fresh |
| Either end route persists <1 s then re-cover | Keep active, reset exit timers |
| Either end route persists 1 s | Remove exact FACE_COVERING |
| Five predicted points but hands still cover | Do not end |
| Unrelated/stale face or ambiguous hands | Do not use as current face/exit proof |
| Explicit target absence / time reset / new track | Clear this person's state/cache |
| Nonfinite or nonpositive timing defaults | Reject configuration |

### 5. Good / Base / Bad Cases

Good: a nose disappears behind hands; current shoulders and both wrists support
covering for 3 s, then hands lower for 1 s and the exact label disappears.
Base: standalone caller lacks face observations; use valid body/hand geometry
and hands-away route, never infer clear-face from guessed pose points.
Bad: clear history on a single missing palm, activate after ten fast frames,
reuse a cached head position indefinitely, or declare the face uncovered merely
because a detector output contains five predicted points.

### 6. Tests Required

- Exact 3 s onset and 1 s exit, different/irregular sampling, unknown pauses,
  late recovery, long gaps, separate end routes, interrupted end and reentry.
- Nose occlusion, mixed hand/pose sources, Stop/mouth-touch/head-hold negatives,
  pseudo-person, same-person association and missing-Z COCO behavior.
- Private normalized five-point Provider flow, current detection association,
  no public coordinate leakage, and formal hand-action route with no detected
  hand points.
- Target absence vs temporary missing pose, per-track isolation and reset.
- Report actual video replay evidence separately from synthetic passing tests.

### 7. Wrong vs Correct

Wrong: `if face_observed: end_covering()` or `if hand is None: clear_history()`.
Correct: use current associated face geometry plus reliable uncovered-hand
observations for 1 s; retain bounded unknown state and count only supported time.

Wrong: validate disappearance with only `hands_covering_face` or a SAD event.
Correct: inspect precise `recognized_actions[name=face_covering]` and the
lifecycle diagnostics, since HANDS_ON_HEAD shares the legacy/event mapping.


## Scenario: Pose-supported hands on head with hand-detector dropouts

### 1. Scope / Trigger

Apply this contract when changing `HANDS_ON_HEAD` scoring, its generic temporal
smoother, or the current-evidence reset in `ActionRecognizer.recognize`. The
rule can score bilateral Pose wrists against both ears even when
HandLandmarker has no current detection for one or both hands.

### 2. Signatures

- `RuleActionClassifier.classify(frame) -> dict[ActionName, float]` computes
  raw `HANDS_ON_HEAD` evidence from the analyzed frame.
- `ActionRecognizer.recognize(frame) -> (ranked_scores, stable_actions,
  fall_status, jump_status)` applies current-evidence resets and temporal
  smoothing before returning exact action labels.
- `ActionSmoother(window_size=10, score_threshold=0.55)` uses an 8-of-10
  activation policy for `HANDS_ON_HEAD`.

### 3. Contracts

- Pose-based `HANDS_ON_HEAD` evidence requires both wrists and both ears. It
  scores the nearer of the same-side and crossed wrist-to-ear pairings after
  normalization by the pose scale; one wrist near the head is insufficient.
- Missing one or both HandLandmarker detections does not by itself clear
  `HANDS_ON_HEAD` history. Missing hand geometry contributes no optional
  hand-center evidence, while valid bilateral Pose evidence can continue to
  accumulate through the 8-of-10 smoother.
- A missing reliable current face anchor immediately clears `HANDS_ON_HEAD`
  history and active state. Track/target resets continue to clear per-target
  action state as before.
- Keep `HANDS_ON_HEAD` as the exact internal/debug action. Preserve the public
  compatibility mapping `HANDS_ON_HEAD -> hands_covering_face` and its current
  formal event route; this rule does not change `FACE_COVERING`'s lifecycle.

### 4. Validation & Error Matrix

| Situation | Required behavior |
|---|---|
| Both Pose wrists and ears support hands on head; either or both HandLandmarker detections are absent | Continue accumulating evidence and stabilize exact `HANDS_ON_HEAD` at the configured 8/10 policy |
| Only one Pose wrist is near the head | Do not stabilize `HANDS_ON_HEAD` |
| Arms are raised away from the head | Do not stabilize `HANDS_ON_HEAD` |
| Reliable face anchor disappears | Immediately clear `HANDS_ON_HEAD` history and active state |
| Current pose disappears | Raw pose score falls to zero; do not retain a stale label after the smoother's deactivation policy |
| Public mapping or formal event is inspected | Both head holding and face covering retain the existing shared compatibility field and route |

### 5. Good / Base / Bad Cases

- Good: both Pose wrists remain beside the ears for 10 frames while one palm
  alternates between detected and missing; exact `HANDS_ON_HEAD` stabilizes.
- Base: both HandLandmarker observations are present; the existing Pose and
  optional hand evidence continue to be smoothed normally.
- Bad: clear all `HANDS_ON_HEAD` votes whenever either hand detector misses, or
  allow one wrist near the head to satisfy the bilateral Pose rule.

### 6. Tests Required

- With bilateral Pose evidence held constant, cover both missing HandLandmarker
  detections and a single missing hand; assert stable exact `HANDS_ON_HEAD`.
- Assert a one-wrist head touch and raised arms away from the head do not
  stabilize the action.
- Assert loss of reliable head/shoulder anchor clears the active action, and
  loss of current pose cannot leave a stale active label.
- Keep the existing assertions for shared legacy mapping and formal event
  routing; inspect `recognized_actions[name=hands_on_head]` when checking the
  exact trigger rather than inferring it from `hands_covering_face`.
- Replay a representative head-holding video and report runtime results
  separately from synthetic test results.

### 7. Wrong vs Correct

Wrong: `if not (left_hand.detected and right_hand.detected):
clear(HANDS_ON_HEAD)` even though bilateral Pose wrists and ears remain valid.
Correct: clear on loss of the reliable current face anchor; otherwise pass the
Pose-based score through the existing temporal smoother.


## Scenario: 2D directional hunch and lying separation

### 1. Scope / Trigger

Apply this contract when changing HUNCHED or LYING geometry, scores, or their
temporal recognition. The same rules apply after MediaPipe-33 and COCO-17 are
mapped into the action engine's common landmark slots.

### 2. Signatures

- `extract_pose_features(landmarks, ...) -> PoseFeatures` derives torso
  orientation and optional signed forward lean from normalized 2D keypoints.
- `RuleActionClassifier.classify(frame) -> dict[ActionName, float]` scores
  HUNCHED and LYING from current pose evidence.
- `ActionSmoother` retains temporal confirmation for stable posture labels.

### 3. Contracts

- Use only normalized x/y coordinates and keypoint confidence for this
  classification. Missing COCO Z is not a reason to disable 2D evidence and
  must never be replaced with fabricated depth.
- With both ears reliable, infer forward direction only when the nose extends
  beyond the bilateral ear x-interval by the configured normalized offset
  (0.08 shoulder widths). If only one ear is reliable, infer direction only
  when the nose extends at least 0.45 shoulder widths beyond that ear. A small
  one-ear offset, frontal face, missing nose, or otherwise ambiguous direction
  leaves signed forward lean unavailable; unsigned torso tilt alone cannot
  prove HUNCHED.
- Score HUNCHED from signed forward torso lean. HEAD_DOWN may contribute as
  supporting evidence but cannot cap the forward-lean score. Preserve temporal
  confirmation so brief bending does not become a stable label.
- Score LYING only when the torso is near horizontal and independent body-layout
  evidence supports lying. Prefer available thigh directions; use shoulder-line
  evidence only when both thigh directions are unavailable. Strong lying
  evidence suppresses HUNCHED. Static lying remains a posture and must not
  create a fall event.
- Preserve public action/event names and existing routing.

### 4. Validation & Error Matrix

| Situation | Required behavior |
|---|---|
| Clear left- or right-facing forward lean | HUNCHED can score without HEAD_DOWN and stabilize after temporal confirmation |
| Backward lean or clear side tilt | Do not score HUNCHED as forward hunch |
| Frontal view, no reliable ear, or unclear face direction | Abstain from directional HUNCHED evidence |
| One reliable ear and nose offset <0.45 shoulder widths | Abstain from directional HUNCHED evidence |
| One reliable ear and nose offset >=0.45 shoulder widths | Use the signed image-space direction, subject to forward torso lean |
| Forward lean with upright/visible thighs | Do not classify as LYING from torso angle alone |
| Near-horizontal torso plus corroborating lower-body layout | LYING may score; suppress HUNCHED |
| Both thigh directions unavailable | Shoulder-line fallback may corroborate LYING |
| Brief lean or static lying | Brief lean does not stabilize; lying does not emit a fall event |

### 5. Good / Base / Bad Cases

- Good: mirrored profile views with a clear nose beyond the ear interval produce
  signed forward lean; visible upright thighs keep the person out of LYING.
- Base: frontal or incomplete face geometry yields no directional hunch score,
  while other posture categories continue to use their available evidence.
- Bad: apply `abs(torso_angle)` as forward lean, let HEAD_DOWN hard-cap HUNCHED,
  or classify a person as LYING from one large torso angle.

### 6. Tests Required

- Cover left/right profile hunch with bilateral ears and with one reliable ear,
  backward lean, side tilt, frontal and small one-ear ambiguity, missing/low-
  confidence landmarks, HEAD_DOWN-independent scoring, and temporal rejection
  of a transient lean.
- Cover upright legs and one-thigh-visible forward lean, clear lying, cropped
  lower-body fallback, and static-lying fall/event regression.
- Run the gesture-pose tests and the full repository suite. Report real-video
  replay separately; synthetic keypoint tests do not establish camera accuracy.

### 7. Wrong vs Correct

Wrong: treat any large absolute shoulder-to-hip angle as HUNCHED or as sufficient
LYING evidence.
Correct: require signed 2D forward direction for HUNCHED and independent body
layout evidence for LYING; abstain when the 2D view cannot establish direction.


## Scenario: Curled-up compact posture with asymmetric lower-body support

### 1. Scope / Trigger

Apply this contract when changing `CURLED_UP` geometry or its temporal
recognition. It covers compact crouches and low, side-supported poses where the
visible legs may be asymmetric and head direction may not be reliable.

### 2. Signatures

- `RuleActionClassifier.classify(frame) -> dict[ActionName, float]` scores
  `CURLED_UP` from shoulder, hip, knee and existing posture geometry.
- `ActionSmoother` retains the existing generic 8-of-10 activation policy at
  score `0.55` for other actions; exact `curled_up` uses its local 3-of-5
  activation policy at the same score threshold.

### 3. Contracts

- Normalize 2D shoulder-to-knee and hip-to-knee distances by the existing torso
  scale. Do not fabricate depth when the source is COCO-17.
- Preserve the existing path where compact shoulder-to-knee geometry is
  supported by `HEAD_DOWN` or `HUNCHED`, but do not require either action for
  every curled pose.
- A second path combines compact shoulder-to-knee geometry (weight `0.35`)
  with lower-body fold evidence (weight `0.65`). Lower-body evidence is the
  strongest available signal from hip-to-knee tuck, bent knees, or near-
  horizontal thighs, capped by support from hip-to-knee tuck or clear torso
  inclination (a `20` to `45` degree ramp). An upright seated torso with long
  hip-to-knee geometry must not qualify merely from bent knees or horizontal
  thighs. Require both signals to contribute at least `0.10`; a
  distant bent knee or compact legs without a fold cannot create a stable
  label by itself.
- When only one side is visible, score each available relation with the
  conservative `0.82` single-side weight. Missing/low-confidence points provide
  no relation and must not be replaced with default coordinates.
- Strong `LYING` suppresses the lower-body-only path when `HEAD_DOWN` and
  `HUNCHED` are both below `0.55`; it does not suppress a separately supported
  curled pose. Do not modify fall detection, priority, or event routing.
- Keep temporal stability specific to `CURLED_UP`: at least 3 of the latest 5
  actual pose-classifier updates must be `>=0.55` to activate; retain 2-of-5
  deactivation hysteresis. Do not change the global window or any other
  action's policy.
- If the same track ID briefly disappears while `CURLED_UP` has qualifying
  votes but is not yet stable, preserve only those pending curl votes for at
  most 4 seconds. Reset
  `FALL`, `JUMPING`, face-covering and all other action history immediately as
  before. Other smoothed actions must collect their complete fresh window;
  zeroed pre-gap frame slots must not shorten confirmation. Never transfer
  votes to a different track ID.
- Preserve `ActionName.CURLED_UP`, `pose_action=body_curled_up`, the existing
  SAD event mapping, identity gate, debug fields, and global action thresholds.

### 4. Validation & Error Matrix

| Situation | Required behavior |
|---|---|
| Compact crouch with folded knees and no visible face | Stable exact `curled_up` after existing temporal confirmation |
| Compact side/asymmetric pose with one reliable lower-body side | Use available evidence with the single-side weight; do not require mirrored knees |
| Only shoulder-to-knee compactness or only lower-body folding is present | Do not stabilize `curled_up` |
| Upright chair sitting with bent knees, horizontal thighs and no hip-to-knee tuck | Keep `SITTING`; do not stabilize `CURLED_UP` |
| Static lying with extended legs and no head/torso curl support | Keep `LYING`; do not stabilize `CURLED_UP` or create FALL |
| Strong `LYING` and no head/torso fold | Suppress the lower-body-only `CURLED_UP` path |
| Missing both hips or both knees | No invented fold evidence |
| Same track returns within 4 seconds after an unconfirmed curl candidate | Pending curl votes may combine; active curl, other actions and fall state start fresh |
| Same track returns after the 4-second curl grace | Start with empty curl history |
| Verified curled videos | Both supplied examples produce a stable `recognized_actions[name=curled_up]` interval without FALL |
| Two of five samples support curl | Keep the exact label inactive; require at least three supported samples |

### 5. Good / Base / Bad Cases

- Good: a low crouch has compact shoulders-to-knees plus folded knees; a
  side-supported pose has compact body geometry and one reliable tucked side.
- Base: a straight-leg side-lying pose remains `LYING`; absent facial evidence
  does not disable valid folded-body evidence.
- Bad: require `HEAD_DOWN` for every curl, treat near-horizontal torso as curl,
  or lower the threshold for all posture actions to catch the two examples.
- Bad: carry candidate curl votes to a new track ID or preserve fall/gesture
  state when retaining the curl vote window.

### 6. Tests Required

- Positive stable-label tests for a compact folded crouch without head/ear
  points and an asymmetric pose with one reliable lower-body side.
- Negative stable-label tests for standing, mirrored upright sitting, forward hunch, static lying and
  isolated compactness/fold evidence and distant bent legs; cover missing
  hips/knees.
- Lifecycle tests for same-ID curl-vote retention within 4 seconds, expiry
  beyond the grace, and immediate reset of unrelated action/event state,
  including a complete fresh confirmation window for unrelated actions.
- Replay the two positive clips and the static-lying/fall negatives. Report
  `recognized_actions`, pose mapping and fall results separately from synthetic
  keypoint tests.

### 7. Wrong vs Correct

Wrong: `min(knee_shoulder_compactness, max(HEAD_DOWN, HUNCHED))` as the only
path, or treating compact knee/hip geometry as sufficient by itself.
Correct: retain that head-supported path and add a bounded second path that
requires both normalized body compactness and independent lower-body folding.
