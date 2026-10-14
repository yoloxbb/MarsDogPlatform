#!/usr/bin/env python3
"""Replay a video through the production RKNN pose/hand and GesturePose paths.

This tool is offline: it reads a video file and never opens a camera or ROS
transport. Its optional landmark trace contains only shoulders, elbows,
wrists, and hand keypoints; face points and image pixels are omitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _parser() -> argparse.ArgumentParser:
    models = REPO_ROOT / "models" / "vision"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument(
        "--pose-model", type=Path,
        default=models / "yolov8n-pose-fp16.rknn",
    )
    parser.add_argument(
        "--hand-detector-model", type=Path,
        default=models / "hand_detector_fp16.rknn",
    )
    parser.add_argument(
        "--hand-landmark-model", type=Path,
        default=models / "hand_landmarks_detector_fp16.rknn",
    )
    parser.add_argument("--frame-stride", type=int, default=2)
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float)
    parser.add_argument("--positive-start-sec", type=float, default=12.0)
    parser.add_argument("--positive-end-sec", type=float, default=20.0)
    parser.add_argument("--preprocessing", choices=("rga", "cpu"), default="rga")
    parser.add_argument("--runtime-library", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--trace-output", type=Path,
        help="Optional privacy-minimized landmark trace for pure rule regression.",
    )
    return parser


def _trace_pose(landmarks: tuple[Any, ...] | None) -> dict[str, list[float]] | None:
    if landmarks is None:
        return None
    # MediaPipe slots corresponding to COCO shoulders, elbows, and wrists.
    return {
        str(index): [
            round(float(landmarks[index].x), 6),
            round(float(landmarks[index].y), 6),
            round(float(landmarks[index].visibility), 5),
            round(float(landmarks[index].presence), 5),
        ]
        for index in (11, 12, 13, 14, 15, 16)
    }


def _trace_hand(landmarks: tuple[Any, ...] | None) -> list[list[float]] | None:
    if landmarks is None:
        return None
    return [
        [round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)]
        for point in landmarks
    ]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _video_frame_range(
    start_sec: float,
    end_sec: float | None,
    fps: float,
    frame_count: int,
) -> tuple[int, int]:
    """Return the clamped absolute half-open frame range for a time window."""

    if fps <= 0.0 or frame_count < 0:
        raise ValueError("video FPS and frame count must be valid")
    if start_sec < 0.0 or (end_sec is not None and end_sec <= start_sec):
        raise ValueError("invalid video time range")
    start_frame = max(0, min(frame_count, math.ceil(start_sec * fps)))
    end_frame = (
        min(frame_count, max(0, math.ceil(end_sec * fps)))
        if end_sec is not None
        else frame_count
    )
    return start_frame, end_frame


def _should_sample_frame(frame_index: int, start_frame: int, stride: int) -> bool:
    """Sample relative to the selected range while retaining absolute indices."""

    if stride < 1:
        raise ValueError("frame stride must be >= 1")
    return frame_index >= start_frame and (frame_index - start_frame) % stride == 0


def run(args: argparse.Namespace) -> dict[str, Any]:
    import cv2

    from marsdog_vision_interaction.providers.hand_backends.factory import (
        create_hand_backend,
    )
    from marsdog_vision_interaction.providers.pose_backends.factory import (
        create_pose_backend,
    )
    from marsdog_vision_interaction.providers.pose_action import PoseActionClassifier
    from marsdog_vision_interaction.providers.vision_observation import (
        VisionObservationProvider,
    )

    from marsdog_vision_interaction.providers.gesture_pose_engine import HandLandmark

    video = args.video.resolve()
    pose_model = args.pose_model.resolve()
    detector_model = args.hand_detector_model.resolve()
    landmark_model = args.hand_landmark_model.resolve()
    model_records = {
        "pose": _model_record(pose_model),
        "hand_detector": _model_record(detector_model),
        "hand_landmarks": _model_record(landmark_model),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "filename": video.name,
            "sha256": _sha256(video) if video.is_file() else None,
        },
        "models": model_records,
        "backend": "rknn",
        "preprocessing": args.preprocessing,
        "frame_stride": args.frame_stride,
        "positive_interval_s": [args.positive_start_sec, args.positive_end_sec],
        "backend_readiness": {"pose": False, "hands": False},
        "errors": [],
        "results": [],
        "landmark_trace": None,
    }
    if args.frame_stride < 1:
        raise ValueError("--frame-stride must be >= 1")
    if args.positive_end_sec <= args.positive_start_sec:
        raise ValueError("positive interval end must follow its start")

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        report["errors"].append({"phase": "video", "error": f"cannot open {video}"})
        return report

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0.0:
        capture.release()
        report["errors"].append({"phase": "video", "error": "video FPS is unavailable"})
        return report
    duration_s = frame_count / fps if frame_count > 0 else None
    start_frame, end_frame = _video_frame_range(
        args.start_sec, args.end_sec, fps, frame_count
    )
    if end_frame <= start_frame:
        capture.release()
        report["errors"].append({"phase": "video", "error": "empty selected video range"})
        return report
    report["video"] = {
        "fps": fps,
        "frame_count": frame_count,
        "duration_s": duration_s,
        "sample_window_s": [start_frame / fps, end_frame / fps],
    }

    pose_backend = None
    hand_backend = None
    trace_samples: list[dict[str, Any]] = []
    result_samples: list[dict[str, Any]] = []
    classifier = PoseActionClassifier()
    try:
        pose_backend = create_pose_backend(
            pose_model,
            rknn_config={"profile": "yolov8n_pose_fp16", "core_mask": "auto"},
            runtime_library=args.runtime_library,
            score_threshold=0.5,
            nms_threshold=0.45,
            max_num_poses=5,
        )
        report["backend_readiness"]["pose"] = True
        hand_backend = create_hand_backend(
            landmark_model,
            detector_model=detector_model,
            running_mode="video",
            rknn_config={"profile": "hand_fp16", "core_mask": "auto"},
            runtime_library=args.runtime_library,
            score_threshold=0.30,
            nms_threshold=0.30,
            presence_threshold=0.50,
            detection_interval=5,
            preprocessing=args.preprocessing,
            max_hands=2,
        )
        report["backend_readiness"]["hands"] = True
        report["hand_backend"] = {
            "name": hand_backend.backend_name,
            "preprocessing": hand_backend.preprocessing_mode,
        }
        report["pose_backend"] = {"name": "rknn", "keypoint_format": "coco_17"}

        if not capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame):
            report["errors"].append({
                "phase": "video",
                "error": f"cannot seek to source frame {start_frame}",
            })
            return report
        frame_index = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES)))
        if frame_index != start_frame:
            report["errors"].append({
                "phase": "video",
                "error": (
                    f"seek landed at frame {frame_index}, expected {start_frame}"
                ),
            })
            return report
        sampled_frames = person_frames = hand_frames = 0
        inference_errors = 0
        started_at = time.perf_counter()
        while frame_index < end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            current_frame = frame_index
            frame_index += 1
            if not _should_sample_frame(current_frame, start_frame, args.frame_stride):
                continue
            timestamp_s = current_frame / fps
            timestamp_ms = int(round(timestamp_s * 1000.0))
            sampled_frames += 1
            height, width = frame.shape[:2]
            pose_results = []
            hand_results = []
            try:
                pose_results = pose_backend.process(frame)
                hand_results = hand_backend.process(frame, mode="video", timestamp_ms=timestamp_ms)
            except Exception as exc:
                inference_errors += 1
                report["errors"].append({
                    "frame_index": current_frame,
                    "timestamp_s": round(timestamp_s, 6),
                    "phase": "inference",
                    "error": str(exc),
                })
            fatal_backend_error = (
                getattr(pose_backend, "fatal_error", None)
                or getattr(hand_backend, "fatal_error", None)
            )
            if fatal_backend_error:
                inference_errors += 1
                report["errors"].append({
                    "frame_index": current_frame,
                    "timestamp_s": round(timestamp_s, 6),
                    "phase": "runtime",
                    "error": str(fatal_backend_error),
                })
                break

            selected_pose = max(pose_results, key=lambda item: float(item.score), default=None)
            pose_landmarks = (
                VisionObservationProvider._coco_behavior_landmarks(
                    [
                        {
                            "id": index,
                            "x": float(point[0]),
                            "y": float(point[1]),
                            "z": None,
                            "confidence": float(point[2]),
                            "presence": float(point[2]),
                        }
                        for index, point in enumerate(selected_pose.keypoints)
                    ]
                )
                if selected_pose is not None
                else None
            )
            left_hand = right_hand = None
            for hand in hand_results:
                slot = hand.handedness.strip().lower()
                landmarks = tuple(
                    HandLandmark(float(point[0]), float(point[1]), float(point[2]))
                    for point in hand.landmarks
                )
                if slot == "left" and left_hand is None:
                    left_hand = landmarks
                elif slot == "right" and right_hand is None:
                    right_hand = landmarks
            person_frames += selected_pose is not None
            hand_frames += bool(hand_results)

            snapshot = classifier.update(
                track_id=1,
                pose_landmarks=pose_landmarks,
                left_hand=left_hand,
                right_hand=right_hand,
                target_present=selected_pose is not None,
                now=timestamp_s,
            )
            raw_score = next(
                (item["score"] for item in snapshot["raw_scores"] if item["name"] == "beckoning"),
                0.0,
            )
            recognized = any(
                item["name"] == "beckoning"
                for item in snapshot["recognized_actions"]
            )
            result_samples.append({
                "frame_index": current_frame,
                "timestamp_s": round(timestamp_s, 6),
                "person_detected": selected_pose is not None,
                "hand_count": len(hand_results),
                "beckoning_raw_score": round(float(raw_score), 6),
                "beckoning_recognized": recognized,
                "pose_action": snapshot["pose_action"],
            })
            if args.trace_output and args.positive_start_sec <= timestamp_s < args.positive_end_sec:
                trace_samples.append({
                    "frame_index": current_frame,
                    "timestamp_s": round(timestamp_s, 6),
                    "pose": _trace_pose(pose_landmarks),
                    "hands": {
                        "left": _trace_hand(left_hand),
                        "right": _trace_hand(right_hand),
                    },
                })
        capture.release()
        report["timing"] = {
            "elapsed_s": round(time.perf_counter() - started_at, 3),
            "source_duration_s": duration_s,
        }
        report["counts"] = {
            "sampled_frames": sampled_frames,
            "person_detected_frames": person_frames,
            "hand_detected_frames": hand_frames,
            "inference_errors": inference_errors,
        }
        report["results"] = result_samples
        positive_hits = [
            item for item in result_samples
            if args.positive_start_sec <= item["timestamp_s"] < args.positive_end_sec
            and item["pose_action"] == "beckoning"
        ]
        report["acceptance"] = {
            "stable_beckoning_in_positive_interval": bool(positive_hits),
            "stable_timestamps_s": [item["timestamp_s"] for item in positive_hits],
            "backend_errors": inference_errors,
        }
        if args.trace_output:
            report["landmark_trace"] = {
                "path": str(args.trace_output.resolve()),
                "sample_count": len(trace_samples),
                "contains_face_landmarks": False,
                "contains_video_frames": False,
            }
            trace = {
                "schema_version": 1,
                "provenance": {
                    "source_filename": video.name,
                    "source_sha256": report["source"]["sha256"],
                    "models": model_records,
                    "backend": "rknn",
                    "preprocessing": hand_backend.preprocessing_mode,
                    "frame_stride": args.frame_stride,
                    "active_interval_s": [args.positive_start_sec, args.positive_end_sec],
                    "contains_face_landmarks": False,
                    "contains_video_frames": False,
                },
                "samples": trace_samples,
            }
            _write_json(args.trace_output, trace)
    except Exception as exc:
        report["errors"].append({"phase": "replay", "error": str(exc)})
    finally:
        capture.release()
        if hand_backend is not None:
            hand_backend.close()
        if pose_backend is not None:
            pose_backend.close()
    return report


def main() -> int:
    args = _parser().parse_args()
    try:
        report = run(args)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "backend": "rknn",
            "backend_readiness": {"pose": False, "hands": False},
            "errors": [{"phase": "startup", "error": str(exc)}],
            "results": [],
        }
    _write_json(args.output, report)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "backend_readiness": report.get("backend_readiness"),
        "counts": report.get("counts"),
        "acceptance": report.get("acceptance"),
        "errors": len(report.get("errors", [])),
    }, sort_keys=True))
    return 0 if report.get("acceptance", {}).get("stable_beckoning_in_positive_interval") and not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
