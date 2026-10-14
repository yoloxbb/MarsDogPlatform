# Repository evidence for owner recall gesture

## Gesture detector output

- `modules/vision/marsdog_vision_interaction/providers/pose_action.py:72-74`
  projects both `ARMS_RAISED` and `WAVING` to public `arm_raise_wave`, while
  `BECKONING` remains the separate public key `beckoning`.
- `pose_action.py:253-264` selects public pose values from the already sorted
  stable `result.actions`; `pose_action.py:423-433` records those stable action
  names in `recognized_actions[]`. `raw_scores[]` is serialized separately at
  `pose_action.py:434-442` and is diagnostic only.
- `vision_observation.py:1313-1341` runs the existing classifier for the
  selected active human's track. The same `action_result` is attached as
  internal `_gesture_diagnostics` at `vision_observation.py:1474`.
- The Vision node calls `_publish_gesture_debug(raw)` before normalizing the
  visual snapshot (`vision_interaction_node.py:1278-1287`), then derives and
  merges public events (`:1307-1336`). `_publish_gesture_debug` reads the
  exact diagnostics at `:1510-1535`. Keep exact gesture names internal; do not
  add debug data to `/perception/visual_event`.
- The existing `vision-gesture-pose` spec documents `beckoning`'s two same-hand
  multi-finger cycles and dynamic 3-of-5 smoother with release below 2/5.
  Reuse the stable output. Do not add event-layer confidence, threshold, or
  release timing. Product decision: stable `beckoning` and `waving` both mean
  recall; `arms_raised` alone does not. The classifier does not infer greeting
  intent from a detected `waving` motion.

## Vision event state and transport

- `vision_interaction_node.py:96-105` defines `/perception/visual_event`
  transport as RELIABLE. `_apply_presence_event_states` at `:120-156` merges
  active state events into `events[]` and `event_instances` before normalizing
  the v1 packet. Preserve this schema and transport.
- `_publish_visual` marks source observations valid only when provider, camera,
  source ID, source age, and current-source owner target provenance are valid
  (`vision_interaction_node.py:1204-1277`). Invalid input must not count as a
  gesture release.
- `OwnerPostureEventState` (`modules/vision/marsdog_vision_interaction/core/
  owner_posture_event_state.py:90-155,170-237`) is the closest source-backed
  state-machine example. Its 1 s entry timing is specific to bend/squat and
  must not be copied for this already-stabilized instantaneous gesture. Reuse
  its source ID idempotence, target binding, invalid-input retention, and
  disarmed-context concepts where applicable.
- Normalization omits private diagnostics: the contract test asserts
  `_gesture_diagnostics` is absent after normalization at
  `modules/vision/tests/test_visual_contract.py:225`.

## Behavior candidate and revalidation path

- `modules/behavior/marsdog_behavior/visual_presence_contract.py:3-27`
  defines current owner/family/stranger qualifiers, presence event names,
  posture-specific events/actions, and the 500 ms target freshness limit.
- `intent_mapper.py:660-803` accepts only `visual_direct` events present in the
  same schema-v1 packet, resolves one qualified target and event instance,
  binds event/epoch/snapshot/source metadata, and creates a
  `visual_direct` `BehaviorCandidate` with config-provided L2 metadata.
  `_visual_presence_target` validates valid observation, event instance,
  epoch/snapshot/source IDs, same-snapshot targets and owner identity at
  `intent_mapper.py:811-890` (continues below this range).
- `perception_client_adapter.py:384-475` revalidates event ID, epoch, snapshot,
  source, active event, target identity/tracking, uniqueness and freshness
  immediately before dispatch. Extend the recognized event set and any
  sequence high-water validation needed for the new event; do not weaken
  existing posture/presence checks.
- `visual_event_consumer.py:173-192` caches active event instance IDs and
  `:371-373` documents retry while a state event stays active, then dedup by
  instance. Preserve one candidate per gesture cycle across repeated 10 Hz
  snapshots and cache interruptions.
- `modules/behavior/config/event_intent_map.yaml:683-697` maps the existing
  owner approach event to `owner_approach_response`,
  `external_interaction`, semantic rank 3, sub-priority 12, safe-point
  interruption. `intent_action_pool.yaml:274-275` selects `approach_owner`.
  Keep those shared-arbitration values for the new interactive gesture route.

## Registered execution capability

- `interfaces/naming/catalog.json:1648-1661` documents the existing bend/squat
  mapping to `approach_owner`; action stages at `:3782-3788` register
  `ACT_INTERACT_APPROACH_OWNER_CLOSER`.
- `modules/action/config/behavior_tree_actions.yaml:1049-1058` defines
  `approach_owner` with only the required approach Action stage.
  `action_catalog.yaml:1415-1421` describes binding a fresh human track and
  navigating to a safe stand-off distance.
- `behavior_tree_actions.yaml:1112-1121` maps `wait_in_place` to
  `ACT_BASIC_WAIT`; this is not a registered owner interaction wait sequence.
  Do not claim a combined approach-and-wait behavior or add motion capability.
- `ACT_VISUAL_RECALL_APPROACH` remains the product candidate label only; it is
  not an event name or registered Action unit.

## Verification boundaries

- Run the requested `python3 tools/dev.py check`, affected Vision and Behavior
  pure suites, and `python3 tools/check_visual_contracts.py`.
- The event contract check protects frozen required fields; do not auto-update
  a frozen baseline. Pure tests and real ROS transport checks are separate,
  and skipped tests are not passes. Do not use hardware or a production ROS
  domain.
