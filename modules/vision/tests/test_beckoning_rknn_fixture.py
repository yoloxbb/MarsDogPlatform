import json
from pathlib import Path

from marsdog_vision_interaction.providers.gesture_pose_engine import (
    HandLandmark,
    PoseLandmark,
)
from marsdog_vision_interaction.providers.pose_action import PoseActionClassifier


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "beckoning"


def test_rknn_beckoning_landmark_fixture_reaches_stable_pose_action() -> None:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text())
    trace = json.loads((FIXTURE_DIR / manifest["fixture"]).read_text())
    interval = manifest["label"]["active_interval_s"]
    assert trace["provenance"]["active_interval_s"] == interval
    assert trace["provenance"]["contains_face_landmarks"] is False
    assert trace["provenance"]["contains_video_frames"] is False
    assert len(trace["samples"]) == manifest["extraction"]["sample_count"]

    classifier = PoseActionClassifier()
    raw_timestamps: list[float] = []
    stable_timestamps: list[float] = []
    for sample in trace["samples"]:
        assert set(sample["pose"]) == {"11", "12", "13", "14", "15", "16"}
        assert "face" not in sample
        pose = [PoseLandmark(0.5, 0.5, None, 0.0, 0.0) for _ in range(33)]
        for index, value in sample["pose"].items():
            pose[int(index)] = PoseLandmark(
                float(value[0]),
                float(value[1]),
                None,
                float(value[2]),
                float(value[3]),
            )
        hands = {
            side: (
                tuple(
                    HandLandmark(float(point[0]), float(point[1]), float(point[2]))
                    for point in landmarks
                )
                if landmarks is not None
                else None
            )
            for side, landmarks in sample["hands"].items()
        }
        assert set(hands) == {"left", "right"}
        assert all(landmarks is None or len(landmarks) == 21 for landmarks in hands.values())
        timestamp = float(sample["timestamp_s"])
        snapshot = classifier.update(
            track_id=1,
            pose_landmarks=tuple(pose),
            left_hand=hands["left"],
            right_hand=hands["right"],
            target_present=True,
            now=timestamp,
        )
        if any(
            item["name"] == "beckoning" and item["score"] >= 0.55
            for item in snapshot["raw_scores"]
        ):
            raw_timestamps.append(timestamp)
        if snapshot["pose_action"] == "beckoning":
            stable_timestamps.append(timestamp)

    assert raw_timestamps
    assert stable_timestamps
    assert all(interval[0] <= timestamp < interval[1] for timestamp in raw_timestamps)
    assert all(interval[0] <= timestamp < interval[1] for timestamp in stable_timestamps)
