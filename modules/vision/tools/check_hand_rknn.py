#!/usr/bin/env python3
"""Check the deployed hand backend on an image or reproducible video.

The command uses the same decoder, ROI geometry, tracking and optional RGA
preprocessor as ``VisionObservationProvider``. Repeated still frames are
reported as a static smoke test; they are not video accuracy evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import statistics
import time
from typing import Any

import cv2
import numpy as np

from marsdog_vision_interaction.providers.hand_backends import create_hand_backend


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, nargs="?", help="BGR image for static smoke")
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parents[2] / "models" / "vision")
    parser.add_argument("--detector", default="hand_detector_fp16.rknn")
    parser.add_argument("--landmarks", default="hand_landmarks_detector_fp16.rknn")
    parser.add_argument("--video", type=Path, help="Optional video instead of repeated still frames")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--preprocessing", choices=("cpu", "rga"), default="cpu")
    parser.add_argument("--mode", choices=("image", "video"), default="video")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--runtime-library", default="")
    return parser


def _hand_record(result: Any) -> dict[str, Any]:
    return {
        "score": float(result.score),
        "presence": float(result.presence),
        "handedness": result.handedness,
        "handedness_score": float(result.handedness_score),
        "box_xywh_normalized": np.asarray(result.box, dtype=np.float32).round(6).tolist() if result.box is not None else None,
        "landmarks": np.asarray(result.landmarks, dtype=np.float32).round(6).tolist(),
    }


def _run_backend(backend: Any, frames: list[np.ndarray], *, warmup: int, mode: str) -> tuple[list[dict[str, Any]], list[float], float]:
    timings: list[float] = []
    records: list[dict[str, Any]] = []
    cpu_start = resource.getrusage(resource.RUSAGE_SELF)
    for index in range(max(0, int(warmup))):
        backend.process(frames[index % len(frames)], mode=mode, timestamp_ms=index + 1)
    for index, frame in enumerate(frames):
        started = time.perf_counter()
        results = backend.process(frame, mode=mode, timestamp_ms=warmup + index + 1)
        timings.append((time.perf_counter() - started) * 1000.0)
        records.append({"hands": [_hand_record(result) for result in results]})
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    cpu_seconds = (cpu_end.ru_utime + cpu_end.ru_stime) - (cpu_start.ru_utime + cpu_start.ru_stime)
    return records, timings, float(cpu_seconds)


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


def main() -> int:
    args = _parser().parse_args()
    frames, input_kind = _load_frames(args)
    detector_path = args.model_dir / args.detector
    landmark_path = args.model_dir / args.landmarks
    backend = create_hand_backend(
        landmark_path,
        detector_model=detector_path,
        running_mode=args.mode,
        rknn_config={"profile": "hand_fp16", "preprocessing": args.preprocessing},
        runtime_library=args.runtime_library,
        preprocessing=args.preprocessing,
    )
    started = time.perf_counter()
    try:
        records, timings, cpu_seconds = _run_backend(backend, frames, warmup=args.warmup, mode=args.mode)
        values = timings[1:] if len(timings) > 1 else timings
        report = {
            "backend": backend.backend_name,
            "preprocessing": backend.preprocessing_mode,
            "detector": str(detector_path),
            "landmarker": str(landmark_path),
            "input": str(args.video or args.image),
            "input_kind": input_kind,
            "shape": list(frames[0].shape),
            "warmup": int(args.warmup),
            "frames": records,
            "median_ms": statistics.median(values) if values else None,
            "p95_ms": float(np.percentile(np.asarray(values), 95)) if values else None,
            "cpu_seconds": cpu_seconds,
            "wall_seconds": time.perf_counter() - started,
            "fatal_error": backend.fatal_error,
        }
    finally:
        backend.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if not report["fatal_error"] and any(frame["hands"] for frame in records) else 2


if __name__ == "__main__":
    raise SystemExit(main())
