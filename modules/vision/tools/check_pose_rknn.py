#!/usr/bin/env python3
"""Smoke test the deployed YOLOv8 pose RKNN backend.

Still-image runs validate model loading, decoding, NMS, geometry and timing.
They do not establish motion accuracy; use ``--video`` for a representative
camera clip when one is available.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time
from typing import Any

import cv2
import numpy as np

from marsdog_vision_interaction.providers.pose_backends import create_pose_backend


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, nargs="?", help="BGR image for static smoke")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "models" / "vision" / "yolov8n-pose-fp16.rknn",
    )
    parser.add_argument("--video", type=Path, help="Optional video instead of repeated still frames")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--score-threshold", type=float, default=0.30)
    parser.add_argument("--nms-threshold", type=float, default=0.45)
    parser.add_argument("--max-num-poses", type=int, default=5)
    parser.add_argument("--runtime-library", default="")
    parser.add_argument("--report", type=Path)
    return parser


def _load_frames(args: argparse.Namespace) -> tuple[list[np.ndarray], str]:
    if args.video is not None:
        capture = cv2.VideoCapture(str(args.video))
        if not capture.isOpened():
            raise SystemExit(f"unable to open video: {args.video}")
        frames: list[np.ndarray] = []
        try:
            while len(frames) < max(1, args.frames):
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(frame)
        finally:
            capture.release()
        if not frames:
            raise SystemExit(f"video contains no readable frames: {args.video}")
        return frames, "video"
    if args.image is None:
        raise SystemExit("an image is required unless --video is supplied")
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"unable to read image: {args.image}")
    return [image] * max(1, args.frames), "static_image"


def _record(result: Any) -> dict[str, Any]:
    return {
        "score": float(result.score),
        "box_xywh_normalized": np.asarray(result.box, dtype=np.float32).round(6).tolist(),
        "keypoints": np.asarray(result.keypoints, dtype=np.float32).round(6).tolist(),
    }


def main() -> int:
    args = _parser().parse_args()
    frames, input_kind = _load_frames(args)
    backend = create_pose_backend(
        args.model,
        rknn_config={"profile": "yolov8n_pose_fp16"},
        runtime_library=args.runtime_library,
        score_threshold=args.score_threshold,
        nms_threshold=args.nms_threshold,
        max_num_poses=args.max_num_poses,
    )
    timings: list[float] = []
    records: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        for index in range(max(0, args.warmup)):
            backend.process(frames[index % len(frames)])
        for frame in frames:
            inference_started = time.perf_counter()
            results = backend.process(frame)
            timings.append((time.perf_counter() - inference_started) * 1000.0)
            records.append({"humans": [_record(result) for result in results]})
        values = timings[1:] if len(timings) > 1 else timings
        report = {
            "backend": backend.backend_name,
            "keypoint_format": backend.keypoint_format,
            "model": str(args.model),
            "input": str(args.video or args.image),
            "input_kind": input_kind,
            "shape": list(frames[0].shape),
            "warmup": int(args.warmup),
            "frames": records,
            "median_ms": statistics.median(values) if values else None,
            "p95_ms": float(np.percentile(np.asarray(values), 95)) if values else None,
            "wall_seconds": time.perf_counter() - started,
            "fatal_error": backend.fatal_error,
        }
    finally:
        backend.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if not report["fatal_error"] and any(frame["humans"] for frame in records) else 2


if __name__ == "__main__":
    raise SystemExit(main())
