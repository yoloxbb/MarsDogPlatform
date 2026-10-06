import pytest

from marsdog_vision_interaction.providers.gesture_pose_engine import (
    ActionName,
    ActionSmoother,
    BehaviorEngine,
    FaceObservation,
    FallEventManager,
    HandLandmark,
    LandmarkFrame,
    PoseLandmark,
)
from marsdog_vision_interaction.providers.pose_action import PoseActionClassifier


def _pose(kind: str = "standing") -> tuple[PoseLandmark, ...]:
    points = [PoseLandmark(0.5, 0.5, 0.0, 0.0, 0.0) for _ in range(33)]

    def set_point(index: int, x: float, y: float, z: float = 0.0) -> None:
        points[index] = PoseLandmark(x, y, z, 1.0, 1.0)

    if kind == "standing":
        values = (
            (0, 0.50, 0.18), (7, 0.46, 0.20), (8, 0.54, 0.20),
            (11, 0.40, 0.30), (12, 0.60, 0.30),
            (13, 0.38, 0.48), (14, 0.62, 0.48),
            (15, 0.38, 0.65), (16, 0.62, 0.65),
            (23, 0.45, 0.55), (24, 0.55, 0.55),
            (25, 0.45, 0.75), (26, 0.55, 0.75),
            (27, 0.45, 0.95), (28, 0.55, 0.95),
        )
    else:
        values = (
            (0, 0.18, 0.75), (7, 0.20, 0.71), (8, 0.20, 0.79),
            (11, 0.30, 0.65), (12, 0.30, 0.85),
            (13, 0.45, 0.65), (14, 0.45, 0.85),
            (15, 0.58, 0.65), (16, 0.58, 0.85),
            (23, 0.70, 0.65), (24, 0.70, 0.85),
            (25, 0.82, 0.65), (26, 0.82, 0.85),
            (27, 0.95, 0.65), (28, 0.95, 0.85),
        )
    for index, x, y in values:
        set_point(index, x, y)
    return tuple(points)


def _pose_with_nose_y(y: float) -> tuple[PoseLandmark, ...]:
    points = list(_pose("standing"))
    nose = points[0]
    points[0] = PoseLandmark(
        nose.x, y, nose.z, nose.visibility, nose.presence
    )
    return tuple(points)


def _profile_hunch(
    *, facing: str = "right", bend: str = "forward"
) -> tuple[PoseLandmark, ...]:
    """Build a 2D profile/oblique pose with an explicit torso direction."""

    points = list(_pose("standing"))
    if facing == "right":
        shoulders = ((11, 0.62, 0.30), (12, 0.82, 0.30))
        hips = ((23, 0.48, 0.55), (24, 0.68, 0.55))
        ears = ((7, 0.56, 0.18), (8, 0.60, 0.18))
        nose = (0.78, 0.16)
    elif facing == "left":
        shoulders = ((11, 0.18, 0.30), (12, 0.38, 0.30))
        hips = ((23, 0.32, 0.55), (24, 0.52, 0.55))
        ears = ((7, 0.40, 0.18), (8, 0.44, 0.18))
        nose = (0.22, 0.16)
    else:
        # A frontal face has no trustworthy 2D facing direction.  Keep the same
        # torso lean as the profile fixture so this test catches abs(angle)
        # regressions instead of passing because the body is upright.
        shoulders = ((11, 0.62, 0.30), (12, 0.82, 0.30))
        hips = ((23, 0.48, 0.55), (24, 0.68, 0.55))
        ears = ((7, 0.46, 0.18), (8, 0.54, 0.18))
        nose = (0.50, 0.16)

    if bend == "backward":
        if facing == "right":
            shoulders = ((11, 0.38, 0.30), (12, 0.58, 0.30))
            hips = ((23, 0.48, 0.55), (24, 0.68, 0.55))
        elif facing == "left":
            shoulders = ((11, 0.42, 0.30), (12, 0.62, 0.30))
            hips = ((23, 0.32, 0.55), (24, 0.52, 0.55))

    for index, x, y in (*shoulders, *hips, *ears, (0, *nose)):
        point = points[index]
        points[index] = PoseLandmark(x, y, point.z, point.visibility, point.presence)
    return tuple(points)


def _pose_with_arms(
    *,
    left_elbow: tuple[float, float],
    right_elbow: tuple[float, float],
    left_wrist: tuple[float, float],
    right_wrist: tuple[float, float],
    wrist_confidence: float = 1.0,
    hip_confidence: float = 1.0,
) -> tuple[PoseLandmark, ...]:
    points = list(_pose("standing"))
    for index, (x, y) in (
        (13, left_elbow),
        (14, right_elbow),
        (15, left_wrist),
        (16, right_wrist),
    ):
        confidence = wrist_confidence if index in (15, 16) else 1.0
        points[index] = PoseLandmark(
            x, y, 0.0, confidence, confidence
        )
    for index in (23, 24):
        point = points[index]
        points[index] = PoseLandmark(
            point.x,
            point.y,
            point.z,
            hip_confidence,
            hip_confidence,
        )
    return tuple(points)


def _curled_fold_pose() -> tuple[PoseLandmark, ...]:
    """Build a low, compact crouch with folded knees and gathered arms."""

    points = list(_pose("standing"))
    for index, x, y in (
        (0, 0.50, 0.31),
        (7, 0.47, 0.23),
        (8, 0.53, 0.23),
        (11, 0.40, 0.30),
        (12, 0.60, 0.30),
        (13, 0.37, 0.37),
        (14, 0.63, 0.37),
        (15, 0.45, 0.43),
        (16, 0.55, 0.43),
        (23, 0.45, 0.47),
        (24, 0.55, 0.47),
        (25, 0.40, 0.50),
        (26, 0.60, 0.50),
        (27, 0.34, 0.70),
        (28, 0.66, 0.70),
    ):
        previous = points[index]
        points[index] = PoseLandmark(x, y, previous.z, 1.0, 1.0)
    return tuple(points)


def _side_supported_fold_pose() -> tuple[PoseLandmark, ...]:
    """Build a side-supported curl with a folded leg and partial compactness."""

    points = list(_pose("standing"))
    for index, x, y in (
        (0, 0.35, 0.83),
        (7, 0.37, 0.74),
        (8, 0.32, 0.91),
        (11, 0.42, 0.69),
        (12, 0.32, 0.72),
        (23, 0.56, 0.70),
        (24, 0.50, 0.74),
        (25, 0.62, 0.83),
        (26, 0.56, 0.85),
        (27, 0.70, 0.78),
        (28, 0.70, 0.77),
    ):
        points[index] = PoseLandmark(x, y, None, 1.0, 1.0)
    return tuple(points)


def _forward_palm(*, curled_ring_finger: bool = False) -> tuple[HandLandmark, ...]:
    """Synthetic camera-facing left palm placed at the left Pose wrist."""

    coordinates = [
        (0.42, 0.42),
        (0.38, 0.39), (0.35, 0.36), (0.33, 0.33), (0.31, 0.30),
        (0.38, 0.36), (0.38, 0.31), (0.38, 0.26), (0.38, 0.21),
        (0.42, 0.35), (0.42, 0.30), (0.42, 0.25), (0.42, 0.19),
        (0.46, 0.36), (0.46, 0.31), (0.46, 0.26), (0.46, 0.21),
        (0.50, 0.37), (0.50, 0.33), (0.50, 0.29), (0.50, 0.24),
    ]
    if curled_ring_finger:
        coordinates[14:17] = [(0.46, 0.32), (0.44, 0.35), (0.46, 0.38)]
    return tuple(HandLandmark(x, y, -0.30) for x, y in coordinates)


def _hand_at(
    center_x: float,
    center_y: float,
) -> tuple[HandLandmark, ...]:
    hand = _forward_palm()
    current_x = sum(point.x for point in hand) / len(hand)
    current_y = sum(point.y for point in hand) / len(hand)
    return tuple(
        HandLandmark(
            point.x + center_x - current_x,
            point.y + center_y - current_y,
            point.z,
        )
        for point in hand
    )


def _forward_palm_at_wrist(
    wrist_x: float,
    wrist_y: float,
) -> tuple[HandLandmark, ...]:
    hand = _forward_palm()
    return tuple(
        HandLandmark(
            point.x + wrist_x - hand[0].x,
            point.y + wrist_y - hand[0].y,
            point.z,
        )
        for point in hand
    )


def _shift_pose(
    pose: tuple[PoseLandmark, ...],
    *,
    dy: float,
    keep_ankles_planted: bool = False,
) -> tuple[PoseLandmark, ...]:
    shifted: list[PoseLandmark] = []
    for index, point in enumerate(pose):
        point_dy = 0.0 if keep_ankles_planted and index in (27, 28) else dy
        shifted.append(
            PoseLandmark(
                point.x,
                point.y + point_dy,
                point.z,
                point.visibility,
                point.presence,
            )
        )
    return tuple(shifted)


def _hide_pose_landmarks(
    pose: tuple[PoseLandmark, ...],
    *indices: int,
) -> tuple[PoseLandmark, ...]:
    hidden = set(indices)
    return tuple(
        PoseLandmark(
            point.x,
            point.y,
            point.z,
            0.0 if index in hidden else point.visibility,
            0.0 if index in hidden else point.presence,
        )
        for index, point in enumerate(pose)
    )


def _shift_selected_pose_landmarks(
    pose: tuple[PoseLandmark, ...],
    indices: tuple[int, ...],
    *,
    dy: float,
) -> tuple[PoseLandmark, ...]:
    selected = set(indices)
    return tuple(
        PoseLandmark(
            point.x,
            point.y + (dy if index in selected else 0.0),
            point.z,
            point.visibility,
            point.presence,
        )
        for index, point in enumerate(pose)
    )


def _face_covering_pose() -> tuple[PoseLandmark, ...]:
    return _pose_with_arms(
        left_elbow=(0.42, 0.31),
        right_elbow=(0.58, 0.31),
        left_wrist=(0.46, 0.21),
        right_wrist=(0.54, 0.21),
    )


def _hands_on_head_pose() -> tuple[PoseLandmark, ...]:
    return _pose_with_arms(
        left_elbow=(0.30, 0.28),
        right_elbow=(0.70, 0.28),
        left_wrist=(0.46, 0.20),
        right_wrist=(0.54, 0.20),
    )


def _clear_face() -> FaceObservation:
    return FaceObservation(
        bbox=(0.40, 0.10, 0.20, 0.20),
        landmarks=(
            (0.445, 0.155),
            (0.555, 0.155),
            (0.500, 0.205),
            (0.460, 0.250),
            (0.540, 0.250),
        ),
        confidence=0.90,
        track_id=7,
    )


def test_standing_action_is_deterministic_and_keeps_public_key() -> None:
    classifier = PoseActionClassifier()
    snapshots = [
        classifier.update(
            track_id=7,
            pose_landmarks=_pose("standing"),
            now=10.0 + index * 0.1,
        )
        for index in range(10)
    ]
    assert snapshots[-1]["pose_action"] == "neutral_stand_sit"
    assert snapshots[-1]["recognized_actions"][0]["name"] == "standing"
    assert {
        item["name"] for item in snapshots[-1]["raw_scores"]
    } == {action.value for action in ActionName}
    assert snapshots[-1]["recognized_actions"][0]["priority"] == "P4"
    assert snapshots[-1]["recognized_actions"][0]["group"] == "posture"
    assert "head_vertical_range_ratio" in snapshots[-1]["temporal_features"]
    assert "ankle_vertical_velocity" in snapshots[-1]["temporal_features"]
    assert "shoulder_vertical_velocity" in snapshots[-1]["temporal_features"]
    assert "torso_scale_change_ratio" in snapshots[-1]["temporal_features"]
    assert snapshots[-1]["fall_detector"]["armed"] is False
    assert snapshots[-1]["fall_detector"]["lying_score"] == 0.0
    assert snapshots[-1]["jump_detector"]["active"] is False
    assert snapshots[-1]["jump_detector"]["mode"] == "full_body"
    assert snapshots[-1]["jump_detector"]["phase"] == "monitoring"
    assert snapshots[-1]["jump_detector"]["missing_landmarks"] == []
    assert set(snapshots[-1]["jump_detector"]["component_scores"]) == {
        "hip_upward",
        "shoulder_upward",
        "ankle_upward",
        "motion_coherence",
        "torso_stability",
        "baseline_displacement",
        "position_return",
    }
    assert snapshots[-1]["hand_features"]["left"]["detected"] is False
    assert (
        snapshots[-1]["hand_features"]["left"][
            "stop_command_zone_score"
        ]
        == 0.0
    )


def test_curled_up_stabilizes_from_compact_folded_pose_without_head_down() -> None:
    pose = _hide_pose_landmarks(_curled_fold_pose(), 0, 7, 8)
    classifier = PoseActionClassifier()
    snapshots = [
        classifier.update(track_id=7, pose_landmarks=pose, now=10.0 + index * 0.1)
        for index in range(12)
    ]

    assert all(
        next(item["score"] for item in snapshot["raw_scores"] if item["name"] == "head_down")
        == 0.0
        for snapshot in snapshots
    )
    assert min(
        next(item["score"] for item in snapshot["raw_scores"] if item["name"] == "curled_up")
        for snapshot in snapshots
    ) >= 0.55
    assert "curled_up" in {
        action["name"] for action in snapshots[-1]["recognized_actions"]
    }


def test_curled_up_stabilizes_with_one_reliable_folded_side() -> None:
    pose = _hide_pose_landmarks(_curled_fold_pose(), 0, 7, 8, 24, 26)
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose)
        )
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.HEAD_DOWN] == 0.0 for result in results)
    assert min(result.raw_score_map[ActionName.CURLED_UP] for result in results) >= 0.55
    assert ActionName.CURLED_UP in {action.name for action in results[-1].actions}


def test_curled_up_stabilizes_from_side_supported_fold_without_head_fold() -> None:
    pose = _side_supported_fold_pose()
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose)
        )
        for index in range(5)
    ]

    assert all(result.raw_score_map[ActionName.HEAD_DOWN] == 0.0 for result in results)
    assert all(result.raw_score_map[ActionName.CURLED_UP] >= 0.55 for result in results)
    assert ActionName.CURLED_UP in {action.name for action in results[-1].actions}


def test_distant_bent_legs_alone_do_not_stabilize_curled_up() -> None:
    points = list(_side_supported_fold_pose())
    for index in (25, 26, 27, 28):
        point = points[index]
        points[index] = PoseLandmark(
            point.x + 0.4,
            point.y,
            point.z,
            point.visibility,
            point.presence,
        )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=tuple(points))
        )
        for index in range(8)
    ]

    assert all(result.raw_score_map[ActionName.CURLED_UP] == 0.0 for result in results)
    assert all(
        ActionName.CURLED_UP not in {action.name for action in result.actions}
        for result in results
    )


@pytest.mark.parametrize(
    "pose",
    (
        _pose("standing"),
        _pose("lying"),
        _profile_hunch(facing="right"),
    ),
    ids=("standing", "static-lying", "forward-hunch"),
)
def test_non_curled_postures_do_not_stabilize_curled_up(
    pose: tuple[PoseLandmark, ...],
) -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.CURLED_UP] < 0.55 for result in results)
    assert all(
        ActionName.CURLED_UP not in {action.name for action in result.actions}
        for result in results
    )


def test_curled_up_does_not_invent_missing_leg_evidence() -> None:
    pose = _hide_pose_landmarks(_curled_fold_pose(), 23, 24, 25, 26)
    engine = BehaviorEngine()
    results = [
        engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.CURLED_UP] == 0.0 for result in results)
    assert all(
        ActionName.CURLED_UP not in {action.name for action in result.actions}
        for result in results
    )


@pytest.mark.parametrize("mirror", (False, True))
def test_upright_seated_pose_does_not_stabilize_curled_up(mirror: bool) -> None:
    points = list(_pose("standing"))
    for index, x, y in (
        (0, 0.42, 0.18),
        (7, 0.40, 0.20),
        (8, 0.44, 0.20),
        (11, 0.40, 0.30),
        (12, 0.45, 0.30),
        (23, 0.40, 0.55),
        (24, 0.45, 0.55),
        (25, 0.65, 0.55),
        (26, 0.70, 0.55),
        (27, 0.65, 0.85),
        (28, 0.70, 0.85),
    ):
        points[index] = PoseLandmark(1.0 - x if mirror else x, y, None, 1.0, 1.0)
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=tuple(points))
        )
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.CURLED_UP] < 0.55 for result in results)
    assert all(
        ActionName.CURLED_UP not in {action.name for action in result.actions}
        for result in results
    )
    assert ActionName.SITTING in {action.name for action in results[-1].actions}


def test_curled_up_temporal_confirmation_uses_three_of_five_not_single_frame() -> None:
    smoother = ActionSmoother()
    raw = {name: 0.0 for name in ActionName}
    raw[ActionName.CURLED_UP] = 0.8
    no_stable_actions = []
    for index in range(5):
        scores = dict(raw)
        if index >= 2:
            scores[ActionName.CURLED_UP] = 0.0
        no_stable_actions.extend(smoother.update(scores, index * 0.1))
    assert ActionName.CURLED_UP not in {action.name for action in no_stable_actions}

    smoother = ActionSmoother()
    stable_actions = []
    for index in range(5):
        scores = dict(raw)
        if index >= 3:
            scores[ActionName.CURLED_UP] = 0.0
        stable_actions = smoother.update(scores, index * 0.1)
    assert ActionName.CURLED_UP in {action.name for action in stable_actions}


def test_track_gap_retains_curl_votes_but_clears_fall_votes() -> None:
    smoother = ActionSmoother()
    raw = {name: 0.0 for name in ActionName}
    raw[ActionName.CURLED_UP] = 0.8
    raw[ActionName.FALL] = 1.0
    stable_actions = ()
    for index in range(5):
        stable_actions = smoother.update(raw, index * 0.1)
    assert {action.name for action in stable_actions} >= {
        ActionName.CURLED_UP,
        ActionName.FALL,
    }

    smoother.retain_only(ActionName.CURLED_UP)
    after_gap = smoother.update(
        {name: 0.0 for name in ActionName}, timestamp_s=0.5
    )

    assert ActionName.CURLED_UP in {action.name for action in after_gap}
    assert ActionName.FALL not in {action.name for action in after_gap}


def test_pose_action_retains_only_pending_curl_votes_across_short_track_gap() -> None:
    classifier = PoseActionClassifier(track_timeout_sec=0.75)
    pose = _side_supported_fold_pose()
    classifier.update(track_id=7, pose_landmarks=pose, now=0.0)
    classifier.update(track_id=7, pose_landmarks=pose, now=0.1)

    classifier.update(track_id=0, pose_landmarks=None, now=2.8)
    resumed = [
        classifier.update(track_id=7, pose_landmarks=pose, now=2.9 + index * 0.1)
        for index in range(3)
    ]

    assert "curled_up" in {
        action["name"]
        for snapshot in resumed
        for action in snapshot["recognized_actions"]
    }
    assert all(not snapshot["fall_event_triggered"] for snapshot in resumed)


@pytest.mark.parametrize(
    "action,window", ((ActionName.STANDING, 10), (ActionName.FALL, 5))
)
def test_retained_curl_votes_do_not_shorten_other_actions_fresh_windows(
    action: ActionName, window: int
) -> None:
    smoother = ActionSmoother()
    raw = {name: 0.0 for name in ActionName}
    raw[ActionName.CURLED_UP] = 0.8
    for index in range(4):
        smoother.update(dict(raw), index * 0.1)
    smoother.retain_only(ActionName.CURLED_UP)

    raw[ActionName.CURLED_UP] = 0.0
    raw[action] = 1.0
    for index in range(1, window + 1):
        stable = smoother.update(dict(raw), 1.0 + index * 0.1)
        assert (action in {item.name for item in stable}) == (index == window)


def test_pose_action_discards_curl_votes_after_grace_expires() -> None:
    classifier = PoseActionClassifier(track_timeout_sec=0.75)
    pose = _side_supported_fold_pose()
    classifier.update(track_id=7, pose_landmarks=pose, now=0.0)
    classifier.update(track_id=7, pose_landmarks=pose, now=0.1)

    classifier.update(track_id=0, pose_landmarks=None, now=4.2)
    resumed = classifier.update(track_id=7, pose_landmarks=pose, now=4.3)

    assert "curled_up" not in {
        action["name"] for action in resumed["recognized_actions"]
    }


def test_pose_action_does_not_carry_active_curl_through_track_loss() -> None:
    classifier = PoseActionClassifier(track_timeout_sec=0.75)
    pose = _side_supported_fold_pose()
    stable = [
        classifier.update(track_id=7, pose_landmarks=pose, now=index * 0.1)
        for index in range(5)
    ]
    assert "curled_up" in {
        action["name"] for action in stable[-1]["recognized_actions"]
    }

    classifier.update(track_id=0, pose_landmarks=None, now=2.8)
    resumed = classifier.update(track_id=7, pose_landmarks=pose, now=2.9)

    assert "curled_up" not in {
        action["name"] for action in resumed["recognized_actions"]
    }


def test_profile_hunch_triggers_without_head_down_for_both_facing_directions() -> None:
    for facing in ("left", "right"):
        engine = BehaviorEngine()
        results = [
            engine.update(
                LandmarkFrame(
                    monotonic_s=0.1 + index * 0.1,
                    pose_landmarks=_profile_hunch(facing=facing),
                )
            )
            for index in range(12)
        ]

        assert results[-1].raw_score_map[ActionName.HEAD_DOWN] == 0.0
        assert results[-1].raw_score_map[ActionName.HUNCHED] >= 0.55
        assert ActionName.HUNCHED in {action.name for action in results[-1].actions}


@pytest.mark.parametrize("facing", ("left", "right"))
def test_hunch_requires_forward_direction_and_reliable_face_orientation(facing: str) -> None:
    engine = BehaviorEngine()
    backward = engine.update(
        LandmarkFrame(
            monotonic_s=0.1,
            pose_landmarks=_profile_hunch(facing=facing, bend="backward"),
        )
    )
    assert backward.raw_score_map[ActionName.HUNCHED] == 0.0

    engine = BehaviorEngine()
    lateral = engine.update(
        LandmarkFrame(
            monotonic_s=0.1,
            pose_landmarks=_profile_hunch(facing="front"),
        )
    )
    assert lateral.raw_score_map[ActionName.HUNCHED] == 0.0

    missing_ears = _hide_pose_landmarks(_profile_hunch(facing="right"), 7, 8)
    engine = BehaviorEngine()
    missing = engine.update(
        LandmarkFrame(monotonic_s=0.1, pose_landmarks=missing_ears)
    )
    assert missing.raw_score_map[ActionName.HUNCHED] == 0.0


def test_small_frontal_nose_offset_inside_ear_interval_is_ambiguous() -> None:
    points = list(_profile_hunch(facing="front"))
    nose = points[0]
    # A small detector asymmetry moves the nose away from the ear midpoint,
    # but it remains between the two ears and cannot establish profile facing.
    points[0] = PoseLandmark(0.52, nose.y, nose.z, nose.visibility, nose.presence)
    pose = tuple(points)
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=0.1 + index * 0.1, pose_landmarks=pose)
        )
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.HUNCHED] == 0.0 for result in results)
    assert all(
        ActionName.HUNCHED not in {action.name for action in result.actions}
        for result in results
    )


@pytest.mark.parametrize("facing", ("left", "right"))
@pytest.mark.parametrize("hidden_ear", (7, 8))
def test_single_ear_clear_profile_still_triggers_hunch(
    facing: str, hidden_ear: int
) -> None:
    pose = tuple(
        PoseLandmark(point.x, point.y, None, point.visibility, point.presence)
        for point in _hide_pose_landmarks(_profile_hunch(facing=facing), hidden_ear)
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=pose,
            )
        )
        for index in range(12)
    ]

    assert results[-1].raw_score_map[ActionName.HUNCHED] >= 0.55
    assert ActionName.HUNCHED in {action.name for action in results[-1].actions}


@pytest.mark.parametrize("hidden_ear", (7, 8))
def test_frontal_single_ear_with_nose_asymmetry_remains_ambiguous(hidden_ear: int) -> None:
    points = list(_profile_hunch(facing="front"))
    point = points[0]
    points[0] = PoseLandmark(0.52, point.y, None, 1.0, 1.0)
    pose = _hide_pose_landmarks(tuple(points), hidden_ear)
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
        assert result.raw_score_map[ActionName.HUNCHED] == 0.0
        assert ActionName.HUNCHED not in {action.name for action in result.actions}


@pytest.mark.parametrize("facing", ("left", "right"))
@pytest.mark.parametrize("visible_ear", (7, 8))
@pytest.mark.parametrize("offset_ratio", (0.44, 0.46, 0.82))
def test_single_ear_direction_requires_large_normalized_offset(
    facing: str, visible_ear: int, offset_ratio: float
) -> None:
    points = list(_profile_hunch(facing=facing))
    shoulder_width = abs(points[12].x - points[11].x)
    direction = -1.0 if facing == "left" else 1.0
    points[0] = PoseLandmark(
        points[visible_ear].x + direction * offset_ratio * shoulder_width,
        points[0].y, None, 1.0, 1.0,
    )
    pose = _hide_pose_landmarks(tuple(points), 8 if visible_ear == 7 else 7)
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
    if offset_ratio < 0.45:
        assert result.raw_score_map[ActionName.HUNCHED] == 0.0
        assert ActionName.HUNCHED not in {action.name for action in result.actions}
    else:
        assert result.raw_score_map[ActionName.HUNCHED] >= 0.55
        assert ActionName.HUNCHED in {action.name for action in result.actions}
    assert result.raw_score_map[ActionName.LYING] == 0.0


@pytest.mark.parametrize("facing", ("left", "right"))
@pytest.mark.parametrize("offset_ratio", (0.07, 0.09))
def test_bilateral_ear_interval_keeps_its_smaller_direction_threshold(
    facing: str, offset_ratio: float
) -> None:
    points = list(_profile_hunch(facing=facing))
    shoulder_width = abs(points[12].x - points[11].x)
    ear_edge = (
        min(points[7].x, points[8].x)
        if facing == "left"
        else max(points[7].x, points[8].x)
    )
    direction = -1.0 if facing == "left" else 1.0
    points[0] = PoseLandmark(
        ear_edge + direction * offset_ratio * shoulder_width,
        points[0].y, None, 1.0, 1.0,
    )
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=tuple(points))
        )
    if offset_ratio < 0.08:
        assert result.raw_score_map[ActionName.HUNCHED] == 0.0
        assert ActionName.HUNCHED not in {action.name for action in result.actions}
    else:
        assert result.raw_score_map[ActionName.HUNCHED] >= 0.55
        assert ActionName.HUNCHED in {action.name for action in result.actions}


@pytest.mark.parametrize("facing", ("left", "right"))
@pytest.mark.parametrize("hidden_ear", (7, 8))
def test_single_ear_profile_backward_lean_remains_negative(
    facing: str, hidden_ear: int
) -> None:
    pose = _hide_pose_landmarks(_profile_hunch(facing=facing, bend="backward"), hidden_ear)
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
        assert result.raw_score_map[ActionName.HUNCHED] == 0.0
        assert ActionName.HUNCHED not in {action.name for action in result.actions}


def test_single_ear_small_nose_offset_remains_ambiguous() -> None:
    points = list(_profile_hunch(facing="right"))
    nose = points[0]
    # The visible ear is x=.56 and the shoulder width is .20.  This .25
    # normalized offset is deliberately below the conservative .45 fallback.
    points[0] = PoseLandmark(0.61, nose.y, nose.z, nose.visibility, nose.presence)
    pose = _hide_pose_landmarks(tuple(points), 8)
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=pose,
            )
        )
        for index in range(12)
    ]

    assert all(result.raw_score_map[ActionName.HUNCHED] == 0.0 for result in results)
    assert all(
        ActionName.HUNCHED not in {action.name for action in result.actions}
        for result in results
    )


def test_transient_forward_hunch_does_not_activate_stable_label() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=(
                    _profile_hunch(facing="right")
                    if index < 4
                    else _pose("standing")
                ),
            )
        )
        for index in range(10)
    ]

    assert max(result.raw_score_map[ActionName.HUNCHED] for result in results) >= 0.55
    assert all(
        ActionName.HUNCHED not in {action.name for action in result.actions}
        for result in results
    )


@pytest.mark.parametrize("facing", ("left", "right"))
@pytest.mark.parametrize("visible_knees", ((25, 26), (25,), (26,)))
def test_deep_profile_hunch_with_rotated_shoulders_and_upright_legs(
    facing: str, visible_knees: tuple[int, ...]
) -> None:
    # A profile shoulder line can rotate without the whole body lying down.
    # This 70-degree bend exceeded the old lying gate.  Keep the legs exactly
    # vertical and use absent Z, as with the production COCO input.
    points = list(_pose("standing"))
    for index, x, y in (
        (0, 0.90, 0.38), (7, 0.82, 0.40), (8, 0.84, 0.40),
        (11, 0.76, 0.44), (12, 0.80, 0.56),
        (23, 0.48, 0.60), (24, 0.52, 0.60),
        (25, 0.48, 0.77), (26, 0.52, 0.77),
        (27, 0.48, 0.94), (28, 0.52, 0.94),
    ):
        points[index] = PoseLandmark(x, y, None, 1.0, 1.0)
    pose = tuple(
        PoseLandmark(
            1.0 - point.x if facing == "left" else point.x,
            point.y,
            None,
            point.visibility,
            point.presence,
        )
        for point in points
    )
    pose = _hide_pose_landmarks(
        pose, 13, 14, 15, 16,
        *(index for index in (25, 26) if index not in visible_knees),
    )
    classifier = PoseActionClassifier()
    for index in range(12):
        classifier.update(
            track_id=7, pose_landmarks=_pose("standing"), now=index * 0.1
        )
    snapshots = [
        classifier.update(track_id=7, pose_landmarks=pose, now=1.2 + index * 0.1)
        for index in range(12)
    ]
    scores = {item["name"]: item["score"] for item in snapshots[-1]["raw_scores"]}
    assert scores["head_down"] == 0.0
    assert scores["hunched"] >= 0.55
    assert scores["lying"] == 0.0
    assert snapshots[-1]["pose_action"] == "hunched_back"
    assert all(
        not snapshot["fall_detector"]["event_triggered"] for snapshot in snapshots
    )


@pytest.mark.parametrize("index", (0, 7, 8))
@pytest.mark.parametrize("confidence_field", ("visibility", "presence"))
def test_weak_nose_or_sole_visible_ear_does_not_support_hunch(
    index: int, confidence_field: str
) -> None:
    pose = _profile_hunch(facing="right")
    if index in (7, 8):
        pose = _hide_pose_landmarks(pose, 8 if index == 7 else 7)
    points = list(pose)
    point = points[index]
    points[index] = PoseLandmark(
        point.x, point.y, None,
        0.49 if confidence_field == "visibility" else 1.0,
        0.49 if confidence_field == "presence" else 1.0,
    )
    engine = BehaviorEngine()
    for frame_index in range(12):
        result = engine.update(
            LandmarkFrame(monotonic_s=frame_index * 0.1, pose_landmarks=tuple(points))
        )
        assert result.raw_score_map[ActionName.HUNCHED] == 0.0
        assert ActionName.HUNCHED not in {action.name for action in result.actions}


def test_cropped_horizontal_body_keeps_shoulder_layout_fallback() -> None:
    engine = BehaviorEngine()
    pose = _hide_pose_landmarks(_pose("lying"), 25, 26, 27, 28)
    for index in range(12):
        result = engine.update(LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=pose))
        assert not result.fall_status.event_triggered
    assert result.raw_score_map[ActionName.LYING] >= 0.55
    assert ActionName.LYING in {action.name for action in result.actions}
    assert ActionName.HUNCHED not in {action.name for action in result.actions}


def test_head_down_and_slumped_shoulders_keep_existing_scores() -> None:
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=_pose_with_nose_y(0.25))
        )
    assert result.raw_score_map[ActionName.HEAD_DOWN] >= 0.55
    assert result.raw_score_map[ActionName.SHOULDERS_SLUMPED] >= 0.55
    assert result.raw_score_map[ActionName.HUNCHED] == 0.0
    assert {ActionName.HEAD_DOWN, ActionName.SHOULDERS_SLUMPED}.issubset(
        action.name for action in result.actions
    )


def test_sitting_keeps_existing_geometry_without_lying_or_hunch() -> None:
    points = list(_pose("standing"))
    for index, x, y in (
        (25, 0.65, 0.55), (26, 0.75, 0.55),
        (27, 0.65, 0.80), (28, 0.75, 0.80),
    ):
        points[index] = PoseLandmark(x, y, None, 1.0, 1.0)
    engine = BehaviorEngine()
    for index in range(12):
        result = engine.update(
            LandmarkFrame(monotonic_s=index * 0.1, pose_landmarks=tuple(points))
        )
    assert ActionName.SITTING in {action.name for action in result.actions}
    assert result.raw_score_map[ActionName.LYING] == 0.0
    assert result.raw_score_map[ActionName.HUNCHED] == 0.0


def test_forward_hunch_with_upright_legs_is_not_lying() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_profile_hunch(facing="right"),
            )
        )
        for index in range(12)
    ]

    assert results[-1].raw_score_map[ActionName.HUNCHED] >= 0.55
    assert results[-1].raw_score_map[ActionName.LYING] == 0.0


def test_horizontal_body_keeps_lying_and_suppresses_hunch() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("lying"),
            )
        )
        for index in range(12)
    ]

    assert results[-1].raw_score_map[ActionName.LYING] >= 0.55
    assert results[-1].raw_score_map[ActionName.HUNCHED] < 0.55
    assert ActionName.LYING in {action.name for action in results[-1].actions}
    assert ActionName.HUNCHED not in {action.name for action in results[-1].actions}


def test_entering_frame_while_lying_never_fabricates_fall_event() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("lying"),
            )
        )
        for index in range(20)
    ]
    assert not any(result.fall_status.event_triggered for result in results)
    assert all(
        ActionName.FALL not in {action.name for action in result.actions}
        for result in results
    )


def test_upright_to_lying_transition_emits_one_fall_edge() -> None:
    engine = BehaviorEngine()
    for index in range(14):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("standing"),
            )
        )

    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.5 + index * 0.1,
                pose_landmarks=_pose("lying"),
            )
        )
        for index in range(15)
    ]
    assert sum(result.fall_status.event_triggered for result in results) == 1
    assert any(result.fall_status.alert_active for result in results)


def test_recent_upright_to_lying_fallback_survives_missing_motion_score(
    monkeypatch,
) -> None:
    # Real PoseLandmarker output can jump directly from a valid upright body to
    # a valid horizontal body without enough adjacent landmarks for velocity.
    monkeypatch.setattr(FallEventManager, "_transition_score", lambda *args: 0.0)
    engine = BehaviorEngine()
    for index in range(14):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("standing"),
            )
        )

    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.5 + index * 0.1,
                pose_landmarks=_pose("lying"),
            )
        )
        for index in range(12)
    ]

    assert sum(result.fall_status.event_triggered for result in results) == 1
    assert any(result.fall_status.phase.value == "falling" for result in results)


def test_fall_transition_survives_brief_pose_occlusion() -> None:
    """A low-FPS fall commonly hides the body before Pose reacquires it lying."""

    engine = BehaviorEngine()
    for index in range(14):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("standing"),
            )
        )

    for timestamp in (1.6, 1.8, 2.0, 2.2):
        engine.update(LandmarkFrame(monotonic_s=timestamp, pose_landmarks=None))
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=2.4 + index * 0.2,
                pose_landmarks=_pose("lying"),
            )
        )
        for index in range(8)
    ]

    assert sum(result.fall_status.event_triggered for result in results) == 1
    assert max(result.fall_status.transition_score for result in results) >= 0.55


def test_fall_confirmation_tolerates_one_noisy_lying_frame() -> None:
    engine = BehaviorEngine()
    for index in range(14):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("standing"),
            )
        )

    kinds = ("lying", "lying", "standing", "lying", "lying", "lying")
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.6 + index * 0.2,
                pose_landmarks=_pose(kind),
            )
        )
        for index, kind in enumerate(kinds)
    ]

    assert sum(result.fall_status.event_triggered for result in results) == 1


def test_fall_confirmation_tolerates_short_upright_looking_pose_noise() -> None:
    engine = BehaviorEngine()
    for index in range(14):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_pose("standing"),
            )
        )

    observations = (
        (1.6, "lying"),
        (1.8, "lying"),
        (2.0, "standing"),
        (2.2, "standing"),
        (2.4, "lying"),
        (2.6, "lying"),
        (2.8, "lying"),
        (3.0, "lying"),
        (3.2, "lying"),
    )
    results = [
        engine.update(
            LandmarkFrame(monotonic_s=timestamp, pose_landmarks=_pose(kind))
        )
        for timestamp, kind in observations
    ]

    assert sum(result.fall_status.event_triggered for result in results) == 1


def test_fall_keeps_armed_track_across_brief_missing_active_target() -> None:
    classifier = PoseActionClassifier(track_timeout_sec=0.75)
    for index in range(14):
        classifier.update(
            track_id=7,
            pose_landmarks=_pose("standing"),
            now=0.1 + index * 0.1,
        )

    for timestamp in (1.6, 1.8, 2.0, 2.2):
        classifier.update(track_id=0, pose_landmarks=None, now=timestamp)
    results = [
        classifier.update(
            track_id=7,
            pose_landmarks=_pose("lying"),
            now=2.4 + index * 0.2,
        )
        for index in range(8)
    ]

    assert sum(bool(result["fall_event_triggered"]) for result in results) == 1
    assert any(result["pose_action"] == "fallen_down" for result in results)


def test_stop_requires_all_four_non_thumb_fingers_to_be_straight() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.41, 0.34),
        right_elbow=(0.62, 0.48),
        left_wrist=(0.42, 0.42),
        right_wrist=(0.62, 0.65),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                left_hand=_forward_palm(curled_ring_finger=True),
            )
        )
        for index in range(8)
    ]

    assert max(result.raw_score_map[ActionName.STOP_GESTURE] for result in results) == 0.0
    assert all(
        ActionName.STOP_GESTURE not in {action.name for action in result.actions}
        for result in results
    )


def test_camera_facing_open_palm_still_triggers_stop() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.41, 0.34),
        right_elbow=(0.62, 0.48),
        left_wrist=(0.42, 0.42),
        right_wrist=(0.62, 0.65),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                left_hand=_forward_palm(),
            )
        )
        for index in range(8)
    ]

    assert any(
        ActionName.STOP_GESTURE in {action.name for action in result.actions}
        for result in results
    )


def test_naturally_lowered_open_hand_does_not_trigger_stop() -> None:
    """A straight resting arm must not count as an intentional command."""

    lowered_wrist = (0.38, 0.67)
    pose = _pose_with_arms(
        left_elbow=(0.38, 0.49),
        right_elbow=(0.62, 0.48),
        left_wrist=lowered_wrist,
        right_wrist=(0.62, 0.65),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                left_hand=_forward_palm_at_wrist(*lowered_wrist),
            )
        )
        for index in range(8)
    ]

    assert max(
        result.raw_score_map[ActionName.STOP_GESTURE]
        for result in results
    ) == 0.0
    assert all(
        ActionName.STOP_GESTURE not in {action.name for action in result.actions}
        for result in results
    )


def test_short_takeoff_is_confirmed_and_held_as_jumping() -> None:
    """Two take-off frames must survive long enough for stable publication."""

    standing = _pose("standing")
    engine = BehaviorEngine()
    for index in range(8):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=standing,
            )
        )

    observations = (
        _shift_pose(standing, dy=-0.05),
        _shift_pose(standing, dy=-0.10),
        _shift_pose(standing, dy=-0.10),
        _shift_pose(standing, dy=-0.08),
        _shift_pose(standing, dy=-0.04),
    )
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.9 + index * 0.1,
                pose_landmarks=pose,
            )
        )
        for index, pose in enumerate(observations)
    ]

    assert sum(result.jump_status.event_triggered for result in results) == 1
    assert any(result.jump_status.active for result in results)
    assert any(
        ActionName.JUMPING in {action.name for action in result.actions}
        for result in results
    )


def test_standing_up_with_planted_feet_is_not_jumping() -> None:
    """Hip-only upward motion is a stand-up, not an airborne take-off."""

    standing = _pose("standing")
    engine = BehaviorEngine()
    for index in range(8):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=standing,
            )
        )
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.9 + index * 0.1,
                pose_landmarks=_shift_pose(
                    standing,
                    dy=-0.05 * (index + 1),
                    keep_ankles_planted=True,
                ),
            )
        )
        for index in range(3)
    ]

    assert not any(result.jump_status.event_triggered for result in results)
    assert all(
        ActionName.JUMPING not in {action.name for action in result.actions}
        for result in results
    )


def test_cropped_upper_body_jump_confirms_after_downward_return() -> None:
    """Missing ankles use coherent shoulder/hip lift plus return evidence."""

    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    engine = BehaviorEngine()
    for index in range(8):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=cropped,
            )
        )

    offsets = (-0.05, -0.10, -0.10, -0.05, -0.02, 0.0, 0.0)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.9 + index * 0.1,
                pose_landmarks=_shift_pose(cropped, dy=offset),
            )
        )
        for index, offset in enumerate(offsets)
    ]

    triggered = [result for result in results if result.jump_status.event_triggered]
    assert len(triggered) == 1
    assert triggered[0].jump_status.mode == "upper_body_fallback"
    assert triggered[0].jump_status.missing_landmarks == (
        "left_ankle",
        "right_ankle",
    )
    assert any(result.jump_status.phase == "awaiting_return" for result in results)
    assert any(
        ActionName.JUMPING in {action.name for action in result.actions}
        for result in results
    )


def test_low_fps_cropped_jump_accepts_one_strong_takeoff_sample() -> None:
    """A short jump must remain observable near the runtime's 5 FPS cadence."""

    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    engine = BehaviorEngine()
    for index in range(4):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.2 + index * 0.2,
                pose_landmarks=cropped,
            )
        )

    observations = (
        (1.0, -0.015),
        (1.2, -0.015),
        (1.4, 0.0),
        (1.6, 0.0),
        (1.8, 0.0),
    )
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=timestamp,
                pose_landmarks=_shift_pose(cropped, dy=offset),
            )
        )
        for timestamp, offset in observations
    ]

    triggered = [result for result in results if result.jump_status.event_triggered]
    assert len(triggered) == 1
    assert triggered[0].jump_status.mode == "upper_body_fallback"
    assert any(
        ActionName.JUMPING in {action.name for action in result.actions}
        for result in results
    )


def test_cropped_standing_up_without_return_is_not_jumping() -> None:
    """A persistent height change must not pass the cropped-body fallback."""

    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    engine = BehaviorEngine()
    for index in range(8):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=cropped,
            )
        )
    offsets = (-0.05, -0.10) + (-0.10,) * 12
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.9 + index * 0.1,
                pose_landmarks=_shift_pose(cropped, dy=offset),
            )
        )
        for index, offset in enumerate(offsets)
    ]

    assert not any(result.jump_status.event_triggered for result in results)
    assert any(
        result.jump_status.rejection_reason == "return_not_observed"
        for result in results
    )
    assert all(
        ActionName.JUMPING not in {action.name for action in result.actions}
        for result in results
    )


def test_missing_hips_cannot_use_upper_body_jump_fallback() -> None:
    cropped = _hide_pose_landmarks(_pose("standing"), 23, 24, 27, 28)
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=_shift_pose(cropped, dy=-0.04 * index),
            )
        )
        for index in range(8)
    ]

    assert results[-1].jump_status.mode == "unavailable"
    assert all(not result.jump_status.event_triggered for result in results)
    assert results[-1].jump_status.rejection_reason == "insufficient_upper_body"


def test_cropped_knee_lift_and_return_triggers_stomping_at_low_fps() -> None:
    """Knee motion is the fallback when a close crop removes both ankles."""

    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    engine = BehaviorEngine()
    for index in range(5):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.2 + index * 0.2,
                pose_landmarks=cropped,
            )
        )

    offsets = (-0.03, -0.06, -0.02, 0.0, 0.0, 0.0, 0.0)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.2 + index * 0.2,
                pose_landmarks=_shift_selected_pose_landmarks(
                    cropped,
                    (25,),
                    dy=offset,
                ),
            )
        )
        for index, offset in enumerate(offsets)
    ]

    assert max(
        result.raw_score_map[ActionName.STOMPING] for result in results
    ) >= 0.55
    assert any(
        ActionName.STOMPING in {action.name for action in result.actions}
        for result in results
    )


def test_cropped_knee_raise_without_return_is_not_stomping() -> None:
    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    engine = BehaviorEngine()
    offsets = (0.0, 0.0, 0.0, -0.05, -0.05, -0.05, -0.05, -0.05)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.2 + index * 0.2,
                pose_landmarks=_shift_selected_pose_landmarks(
                    cropped,
                    (25,),
                    dy=offset,
                ),
            )
        )
        for index, offset in enumerate(offsets)
    ]

    assert max(
        result.raw_score_map[ActionName.STOMPING] for result in results
    ) == 0.0
    assert all(
        ActionName.STOMPING not in {action.name for action in result.actions}
        for result in results
    )


def test_cropped_stomp_diagnostics_report_knee_fallback() -> None:
    cropped = _hide_pose_landmarks(_pose("standing"), 27, 28)
    classifier = PoseActionClassifier()
    snapshots = []
    offsets = (0.0, 0.0, 0.0, -0.03, -0.06, -0.02, 0.0, 0.0, 0.0)
    for index, offset in enumerate(offsets):
        snapshots.append(
            classifier.update(
                track_id=7,
                pose_landmarks=_shift_selected_pose_landmarks(
                    cropped,
                    (25,),
                    dy=offset,
                ),
                now=0.2 + index * 0.2,
            )
        )

    assert snapshots[-1]["stomp_detector"]["source"] == "knee_fallback"
    assert snapshots[-1]["stomp_detector"]["knee_direction_changes"] >= 1
    assert any(snapshot["stomp_detector"]["recognized"] for snapshot in snapshots)


def test_single_frame_full_body_shift_does_not_trigger_jump() -> None:
    """One camera/body-position discontinuity is not a confirmed take-off."""

    standing = _pose("standing")
    engine = BehaviorEngine()
    for index in range(8):
        engine.update(
            LandmarkFrame(
                monotonic_s=0.1 + index * 0.1,
                pose_landmarks=standing,
            )
        )
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=0.9,
                pose_landmarks=_shift_pose(standing, dy=-0.08),
            )
        ),
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0,
                pose_landmarks=standing,
            )
        ),
    ]

    assert not any(result.jump_status.event_triggered for result in results)
    assert all(
        ActionName.JUMPING not in {action.name for action in result.actions}
        for result in results
    )


def test_elevated_camera_bent_elbow_open_palm_triggers_stop() -> None:
    """A dog-head camera must tolerate foreshortening and a bent raised arm."""

    raised_palm = _hand_at(0.42, 0.30)
    pose = _pose_with_arms(
        left_elbow=(0.50, 0.28),
        right_elbow=(0.62, 0.48),
        left_wrist=(raised_palm[0].x, raised_palm[0].y),
        right_wrist=(0.62, 0.65),
        wrist_confidence=0.62,
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                left_hand=raised_palm,
            )
        )
        for index in range(8)
    ]

    assert any(
        ActionName.STOP_GESTURE in {action.name for action in result.actions}
        for result in results
    )


def test_crossed_arms_open_palm_does_not_trigger_stop() -> None:
    crossed_pose = _pose_with_arms(
        left_elbow=(0.58, 0.42),
        right_elbow=(0.42, 0.42),
        left_wrist=(0.42, 0.42),
        right_wrist=(0.58, 0.42),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=crossed_pose,
                left_hand=_forward_palm(),
            )
        )
        for index in range(8)
    ]

    assert min(
        result.raw_score_map[ActionName.ARMS_CROSSED]
        for result in results
    ) >= 0.40
    assert max(
        result.raw_score_map[ActionName.STOP_GESTURE]
        for result in results
    ) == 0.0
    assert all(
        ActionName.STOP_GESTURE not in {action.name for action in result.actions}
        for result in results
    )


def test_face_covering_uses_bilateral_pose_fallback_when_hands_missing() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=_face_covering_pose(),
                target_present=True,
            )
        )
        for index in range(32)
    ]

    assert all(
        ActionName.FACE_COVERING not in {action.name for action in result.actions}
        for result in results[:30]
    )
    assert ActionName.FACE_COVERING in {
        action.name for action in results[-1].actions
    }


def test_face_covering_geometry_handles_hidden_nose_and_mixed_sources() -> None:
    pose = _hide_pose_landmarks(_face_covering_pose(), 0, 7, 8)
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=pose,
            left_hand=_hand_at(0.46, 0.21),
            target_present=True,
        )
    )

    evidence = result.face_covering_detector
    assert evidence["category"] == "cover"
    assert evidence["region_source"] == "pose"
    assert evidence["left_source"] == "hand"
    assert evidence["right_source"] == "pose_wrist"


def test_face_covering_geometry_requires_bilateral_current_arm_evidence() -> None:
    pose = _hide_pose_landmarks(_face_covering_pose(), 16)
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=pose,
            left_hand=_hand_at(0.46, 0.21),
            target_present=True,
        )
    )

    assert result.face_covering_detector["category"] == "unknown"
    assert result.face_covering_detector["right_source"] == "unknown"


def test_face_covering_rejects_minuscule_pseudo_person_geometry() -> None:
    pose = tuple(
        PoseLandmark(
            0.5 + (point.x - 0.5) * 0.10,
            0.5 + (point.y - 0.5) * 0.10,
            point.z,
            point.visibility,
            point.presence,
        )
        for point in _face_covering_pose()
    )
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=pose,
            target_present=True,
        )
    )

    assert result.face_covering_detector["category"] == "unknown"
    assert result.face_covering_detector["region_source"] == "none"


def test_cached_face_region_rejects_large_torso_motion() -> None:
    engine = BehaviorEngine()
    first = engine.update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=_face_covering_pose(),
            target_present=True,
        )
    )
    assert first.face_covering_detector["region_source"] == "pose"

    shifted_hidden = tuple(
        PoseLandmark(
            point.x + 0.20,
            point.y,
            point.z,
            0.0 if index in (0, 7, 8) else point.visibility,
            0.0 if index in (0, 7, 8) else point.presence,
        )
        for index, point in enumerate(_face_covering_pose())
    )
    moved = engine.update(
        LandmarkFrame(
            monotonic_s=1.1,
            pose_landmarks=shifted_hidden,
            target_present=True,
        )
    )

    assert moved.face_covering_detector["region_source"] == "pose"


def test_no_z_open_forward_palms_with_straight_arms_are_not_covering() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.43, 0.255),
        right_elbow=(0.57, 0.255),
        left_wrist=(0.46, 0.21),
        right_wrist=(0.54, 0.21),
    )
    no_depth = tuple(
        PoseLandmark(
            point.x,
            point.y,
            None,
            point.visibility,
            point.presence,
        )
        for point in pose
    )
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=no_depth,
            left_hand=_forward_palm_at_wrist(0.46, 0.21),
            right_hand=_forward_palm_at_wrist(0.54, 0.21),
            target_present=True,
        )
    )

    assert result.face_covering_detector["category"] != "cover"


def test_foreign_face_hands_do_not_override_same_person_pose_arms() -> None:
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=_pose("standing"),
            # Both independent hands appear over the face, but their wrists
            # do not associate with this person's current pose wrists.
            left_hand=_hand_at(0.46, 0.21),
            right_hand=_hand_at(0.54, 0.21),
            target_present=True,
        )
    )

    evidence = result.face_covering_detector
    assert evidence["category"] != "cover"
    assert evidence["left_source"] == "pose_wrist_fallback"
    assert evidence["right_source"] == "pose_wrist_fallback"


def test_touching_cheeks_or_holding_head_is_not_face_covering() -> None:
    for left_wrist, right_wrist in (
        ((0.38, 0.20), (0.62, 0.20)),
        ((0.40, 0.10), (0.60, 0.10)),
    ):
        pose = _pose_with_arms(
            left_elbow=(0.40, 0.28),
            right_elbow=(0.60, 0.28),
            left_wrist=left_wrist,
            right_wrist=right_wrist,
        )
        engine = BehaviorEngine()
        for index in range(32):
            result = engine.update(
                LandmarkFrame(
                    monotonic_s=1.0 + index * 0.1,
                    pose_landmarks=pose,
                    target_present=True,
                )
            )

        assert result.face_covering_detector["category"] != "cover"
        assert ActionName.FACE_COVERING not in {
            action.name for action in result.actions
        }


def test_predicted_five_point_face_does_not_end_while_hands_still_cover() -> None:
    engine = BehaviorEngine()
    for index in range(32):
        result = engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=_face_covering_pose(),
                left_hand=_hand_at(0.46, 0.21),
                right_hand=_hand_at(0.54, 0.21),
                face_observation=_clear_face(),
                target_present=True,
            )
        )

    assert result.face_covering_detector["category"] == "cover"
    assert result.face_covering_detector["current_face"] is True
    assert ActionName.FACE_COVERING in {action.name for action in result.actions}


def test_clear_face_needs_both_hands_outside_cover_region() -> None:
    moderate_pose = _pose_with_arms(
        left_elbow=(0.36, 0.28),
        right_elbow=(0.64, 0.28),
        left_wrist=(0.29, 0.18),
        right_wrist=(0.71, 0.18),
    )
    result = BehaviorEngine().update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=moderate_pose,
            face_observation=_clear_face(),
            target_present=True,
        )
    )

    evidence = result.face_covering_detector
    assert evidence["category"] == "clear"
    assert evidence["left_cover_score"] <= 0.20
    assert evidence["right_cover_score"] <= 0.20


def test_face_covering_clears_when_target_is_confirmed_absent() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=_face_covering_pose(),
                left_hand=_hand_at(0.46, 0.21),
                right_hand=_hand_at(0.54, 0.21),
                target_present=True,
            )
        )
        for index in range(32)
    ]
    assert ActionName.FACE_COVERING in {
        action.name for action in results[-1].actions
    }

    hands_without_person = engine.update(
        LandmarkFrame(
            monotonic_s=4.2,
            pose_landmarks=None,
            left_hand=_hand_at(0.46, 0.21),
            right_hand=_hand_at(0.54, 0.21),
            target_present=False,
        )
    )

    assert (
        hands_without_person.raw_score_map[ActionName.FACE_COVERING]
        == 0.0
    )
    assert ActionName.FACE_COVERING not in {
        action.name for action in hands_without_person.actions
    }


def test_hands_on_head_survives_missing_hand_landmarker_observations() -> None:
    pose = _hands_on_head_pose()
    for left_hand, right_hand in (
        (None, None),
        (None, _hand_at(0.54, 0.20)),
        (_hand_at(0.46, 0.20), None),
    ):
        engine = BehaviorEngine()
        results = [
            engine.update(
                LandmarkFrame(
                    monotonic_s=1.0 + index * 0.1,
                    pose_landmarks=pose,
                    left_hand=left_hand,
                    right_hand=right_hand,
                    face_observed=True,
                )
            )
            for index in range(10)
        ]

        assert all(
            result.raw_score_map[ActionName.HANDS_ON_HEAD] >= 0.55
            for result in results
        )
        assert ActionName.HANDS_ON_HEAD in {
            action.name for action in results[-1].actions
        }


def test_hands_on_head_clears_when_reliable_pose_anchor_is_lost() -> None:
    pose = _hands_on_head_pose()
    for missing_pose in (
        _hide_pose_landmarks(pose, 0),
        _hide_pose_landmarks(pose, 11, 12),
        None,
    ):
        engine = BehaviorEngine()
        for index in range(10):
            active = engine.update(
                LandmarkFrame(
                    monotonic_s=1.0 + index * 0.1,
                    pose_landmarks=pose,
                    face_observed=True,
                )
            )
        assert ActionName.HANDS_ON_HEAD in {
            action.name for action in active.actions
        }

        lost = engine.update(
            LandmarkFrame(monotonic_s=2.0, pose_landmarks=missing_pose)
        )
        assert ActionName.HANDS_ON_HEAD not in {
            action.name for action in lost.actions
        }

        recovered = engine.update(
            LandmarkFrame(monotonic_s=2.1, pose_landmarks=pose)
        )
        assert recovered.raw_score_map[ActionName.HANDS_ON_HEAD] >= 0.55
        assert ActionName.HANDS_ON_HEAD not in {
            action.name for action in recovered.actions
        }


def test_hands_on_head_rejects_single_hand_near_head() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.30, 0.28),
        right_elbow=(0.62, 0.48),
        left_wrist=(0.46, 0.20),
        right_wrist=(0.62, 0.65),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                face_observed=True,
            )
        )
        for index in range(10)
    ]

    assert max(
        result.raw_score_map[ActionName.HANDS_ON_HEAD] for result in results
    ) < 0.55
    assert all(
        ActionName.HANDS_ON_HEAD not in {action.name for action in result.actions}
        for result in results
    )


def test_hands_on_head_rejects_arms_raised_away_from_head() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.30, 0.22),
        right_elbow=(0.70, 0.22),
        left_wrist=(0.25, 0.10),
        right_wrist=(0.75, 0.10),
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                face_observed=True,
            )
        )
        for index in range(10)
    ]

    assert max(
        result.raw_score_map[ActionName.HANDS_ON_HEAD] for result in results
    ) < 0.55
    assert all(
        ActionName.HANDS_ON_HEAD not in {action.name for action in result.actions}
        for result in results
    )


def test_pose_fallback_face_covering_still_publishes_hand_action_without_hands() -> None:
    classifier = PoseActionClassifier()
    snapshot = {}
    for index in range(32):
        snapshot = classifier.update(
            track_id=11,
            pose_landmarks=_face_covering_pose(),
            target_present=True,
            now=1.0 + index * 0.1,
        )

    assert snapshot["hand_action"] == "hands_covering_face"
    assert snapshot["face_covering_detector"]["active"] is True


def test_face_covering_timing_is_isolated_per_target_and_timestamp_restart() -> None:
    classifier = PoseActionClassifier()
    for index in range(30):
        first = classifier.update(
            track_id=11,
            pose_landmarks=_face_covering_pose(),
            target_present=True,
            now=1.0 + index * 0.1,
        )
    assert first["face_covering_detector"]["active"] is False

    second = classifier.update(
        track_id=12,
        pose_landmarks=_face_covering_pose(),
        target_present=True,
        now=4.0,
    )
    assert second["face_covering_detector"]["state"] == "candidate"
    assert second["face_covering_detector"]["active"] is False

    first = classifier.update(
        track_id=11,
        pose_landmarks=_face_covering_pose(),
        target_present=True,
        now=4.0,
    )
    assert first["face_covering_detector"]["active"] is True

    restarted = classifier.update(
        track_id=11,
        pose_landmarks=_face_covering_pose(),
        target_present=True,
        now=1.0,
    )
    assert restarted["face_covering_detector"]["state"] == "candidate"
    assert restarted["face_covering_detector"]["active"] is False


def test_stop_is_cleared_immediately_when_no_hand_is_observed() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.41, 0.34),
        right_elbow=(0.62, 0.48),
        left_wrist=(0.42, 0.42),
        right_wrist=(0.62, 0.65),
    )
    engine = BehaviorEngine()
    for index in range(6):
        result = engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=pose,
                left_hand=_forward_palm(),
            )
        )
    assert ActionName.STOP_GESTURE in {action.name for action in result.actions}

    no_hand_result = engine.update(
        LandmarkFrame(monotonic_s=1.6, pose_landmarks=pose)
    )

    assert no_hand_result.raw_score_map[ActionName.STOP_GESTURE] == 0.0
    assert ActionName.STOP_GESTURE not in {
        action.name for action in no_hand_result.actions
    }


def test_stop_rejects_low_confidence_wrist_from_cropped_upper_body() -> None:
    """A HandLandmarker false positive must not pair with a guessed Pose wrist."""

    cropped_pose = _pose_with_arms(
        left_elbow=(0.41, 0.34),
        right_elbow=(0.62, 0.48),
        left_wrist=(0.42, 0.42),
        right_wrist=(0.62, 0.65),
        wrist_confidence=0.55,
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index * 0.1,
                pose_landmarks=cropped_pose,
                left_hand=_forward_palm(),
            )
        )
        for index in range(8)
    ]

    assert max(result.raw_score_map[ActionName.STOP_GESTURE] for result in results) == 0.0
    assert all(
        ActionName.STOP_GESTURE not in {action.name for action in result.actions}
        for result in results
    )


def test_small_nose_keypoint_jitter_does_not_trigger_fast_nod() -> None:
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=_pose_with_nose_y(
                    0.174 if index % 2 else 0.186
                ),
            )
        )
        for index in range(20)
    ]
    assert all(
        ActionName.FAST_NOD not in {action.name for action in result.actions}
        for result in results
    )
    assert results[-1].raw_score_map[ActionName.FAST_NOD] < 0.55
    assert results[-1].features.temporal.head_vertical_direction_changes > 0


def test_deliberate_head_vertical_cycle_can_trigger_fast_nod() -> None:
    engine = BehaviorEngine()
    cycle = (0.18, 0.21, 0.24, 0.21, 0.18)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=_pose_with_nose_y(cycle[index % len(cycle)]),
            )
        )
        for index in range(20)
    ]
    assert any(
        ActionName.FAST_NOD in {action.name for action in result.actions}
        for result in results
    )


def test_hand_only_pose_false_positive_cannot_trigger_fast_nod() -> None:
    engine = BehaviorEngine()
    cycle = (0.18, 0.21, 0.24, 0.21, 0.18)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                # Simulate PoseLandmarker fitting a moving hand as a person.
                pose_landmarks=_pose_with_nose_y(
                    cycle[index % len(cycle)]
                ),
                left_hand=_hand_at(0.50, 0.30),
                face_observed=False,
            )
        )
        for index in range(20)
    ]

    assert max(
        result.raw_score_map[ActionName.FAST_NOD]
        for result in results
    ) == 0.0
    assert all(
        ActionName.FAST_NOD not in {action.name for action in result.actions}
        for result in results
    )


def test_fast_nod_clears_immediately_when_face_disappears() -> None:
    engine = BehaviorEngine()
    cycle = (0.18, 0.21, 0.24, 0.21, 0.18)
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=_pose_with_nose_y(
                    cycle[index % len(cycle)]
                ),
                face_observed=True,
            )
        )
        for index in range(20)
    ]
    assert ActionName.FAST_NOD in {
        action.name for action in results[-1].actions
    }

    hand_only = engine.update(
        LandmarkFrame(
            monotonic_s=2.4,
            pose_landmarks=_pose_with_nose_y(0.24),
            left_hand=_hand_at(0.50, 0.30),
            face_observed=False,
        )
    )

    assert hand_only.raw_score_map[ActionName.FAST_NOD] == 0.0
    assert ActionName.FAST_NOD not in {
        action.name for action in hand_only.actions
    }


def test_crossing_arms_does_not_trigger_clapping() -> None:
    engine = BehaviorEngine()
    wrist_pairs = (
        ((0.38, 0.44), (0.62, 0.44)),
        ((0.43, 0.44), (0.57, 0.44)),
        ((0.48, 0.44), (0.52, 0.44)),
        ((0.52, 0.44), (0.48, 0.44)),
        ((0.57, 0.44), (0.43, 0.44)),
        ((0.59, 0.44), (0.41, 0.44)),
    )
    frames = list(wrist_pairs) + [wrist_pairs[-1]] * 10
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=_pose_with_arms(
                    left_elbow=(0.34, 0.42),
                    right_elbow=(0.66, 0.42),
                    left_wrist=left_wrist,
                    right_wrist=right_wrist,
                ),
            )
        )
        for index, (left_wrist, right_wrist) in enumerate(frames)
    ]
    assert max(
        result.features.temporal.wrist_distance_direction_changes
        for result in results
    ) == 1
    assert all(
        ActionName.CLAPPING not in {action.name for action in result.actions}
        for result in results
    )
    assert ActionName.ARMS_CROSSED in {
        action.name for action in results[-1].actions
    }


def test_occluded_hands_on_hips_remains_recognizable() -> None:
    pose = _pose_with_arms(
        left_elbow=(0.27, 0.43),
        right_elbow=(0.73, 0.43),
        left_wrist=(0.36, 0.50),
        right_wrist=(0.64, 0.50),
        wrist_confidence=0.35,
        hip_confidence=0.40,
    )
    engine = BehaviorEngine()
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=pose,
            )
        )
        for index in range(12)
    ]
    recognized = {action.name for action in results[-1].actions}
    assert ActionName.HANDS_ON_HIPS in recognized
    assert ActionName.ARMS_CROSSED not in recognized
    assert ActionName.ARMS_OPEN not in recognized


def test_repeated_hand_open_close_still_triggers_clapping() -> None:
    engine = BehaviorEngine()
    hand_distances = (
        0.20,
        0.12,
        0.04,
        0.12,
        0.20,
        0.12,
        0.04,
        0.12,
        0.20,
        0.12,
        0.04,
        0.12,
        0.20,
    ) * 2
    results = [
        engine.update(
            LandmarkFrame(
                monotonic_s=1.0 + index / 15.0,
                pose_landmarks=_pose_with_arms(
                    left_elbow=(0.37, 0.42),
                    right_elbow=(0.63, 0.42),
                    left_wrist=(0.50 - distance / 2.0, 0.44),
                    right_wrist=(0.50 + distance / 2.0, 0.44),
                ),
            )
        )
        for index, distance in enumerate(hand_distances)
    ]
    assert any(
        ActionName.CLAPPING in {action.name for action in result.actions}
        for result in results
    )
    assert all(
        ActionName.ARMS_CROSSED not in {action.name for action in result.actions}
        for result in results
    )
