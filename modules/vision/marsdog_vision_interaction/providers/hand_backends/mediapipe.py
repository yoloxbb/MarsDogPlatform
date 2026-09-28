"""Lazy MediaPipe Tasks hand adapter used by the explicit ``.task`` rollback."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .base import HandBackend, HandBackendError, HandResult, validate_frame

logger = logging.getLogger(__name__)


class MediaPipeHandBackend(HandBackend):
    backend_name = "mediapipe"

    def __init__(
        self,
        model_path: str | Path,
        *,
        running_mode: str = "video",
        score_threshold: float = 0.5,
        presence_threshold: float = 0.5,
        tracking_threshold: float = 0.5,
        max_hands: int = 2,
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._fatal_error: str | None = None
        self._running_mode = str(running_mode).strip().lower()
        if self._running_mode not in {"image", "video"}:
            raise ValueError("hand running_mode must be image or video")
        self._presence_threshold = float(presence_threshold)
        self._timestamp_ms = 0
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.vision import RunningMode

            mode = RunningMode.VIDEO if self._running_mode == "video" else RunningMode.IMAGE
            options = vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mode,
                num_hands=max(1, min(2, int(max_hands))),
                min_hand_detection_confidence=float(score_threshold),
                min_hand_presence_confidence=float(presence_threshold),
                min_tracking_confidence=float(tracking_threshold),
            )
            self._mp = mp
            self._landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as exc:
            self._closed = True
            raise HandBackendError(f"MediaPipe hand model initialization failed: {exc}") from exc

    @property
    def fatal_error(self) -> str | None:
        return self._fatal_error

    def _next_timestamp(self) -> int:
        value = time.monotonic_ns() // 1_000_000
        if value <= self._timestamp_ms:
            value = self._timestamp_ms + 1
        self._timestamp_ms = value
        return value

    def process(self, frame: np.ndarray, *, mode: str | None = None, timestamp_ms: int | None = None) -> list[HandResult]:
        image = validate_frame(frame)
        with self._lock:
            if self._closed or self._landmarker is None:
                return []
            try:
                rgb = np.ascontiguousarray(image[:, :, ::-1])
                mp_image = self._mp.Image(
                    image_format=self._mp.ImageFormat.SRGB,
                    data=rgb,
                )
                running_mode = str(mode or self._running_mode).strip().lower()
                if running_mode == "video":
                    if timestamp_ms is not None:
                        requested = int(timestamp_ms)
                        if requested <= self._timestamp_ms:
                            # Tasks VIDEO rejects backwards timestamps.  A
                            # backwards source timestamp starts a fresh
                            # logical sequence while the adapter keeps the
                            # API timestamp monotonic for the live context.
                            requested = self._next_timestamp()
                        else:
                            self._timestamp_ms = requested
                        timestamp_ms = requested
                    result = self._landmarker.detect_for_video(
                        mp_image, int(timestamp_ms) if timestamp_ms is not None else self._next_timestamp()
                    )
                else:
                    result = self._landmarker.detect(mp_image)
                return self._convert(result)
            except Exception as exc:
                # MediaPipe's malformed frame errors are recoverable.  The
                # context remains usable for the next complete frame.
                logger.debug("MediaPipe hand inference error: %s", exc)
                return []

    def _convert(self, result: Any) -> list[HandResult]:
        output: list[HandResult] = []
        for index, landmarks in enumerate(getattr(result, "hand_landmarks", ()) or ()):
            if len(landmarks) != 21:
                continue
            rows = np.asarray(
                [[float(point.x), float(point.y), float(point.z)] for point in landmarks],
                dtype=np.float32,
            )
            category = ""
            category_score = 0.0
            handedness = getattr(result, "handedness", ()) or ()
            if index < len(handedness) and handedness[index]:
                category_obj = handedness[index][0]
                category = str(getattr(category_obj, "category_name", ""))
                category_score = float(getattr(category_obj, "score", 0.0) or 0.0)
            # Tasks already applies the presence threshold.  Some versions do
            # not expose per-hand presence; use one as the contract value.
            output.append(
                HandResult(
                    landmarks=rows,
                    handedness=category,
                    handedness_score=category_score,
                    score=category_score,
                    presence=1.0,
                )
            )
        return output[:2]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            landmarker, self._landmarker = self._landmarker, None
            if landmarker is not None:
                try:
                    landmarker.close()
                except Exception:
                    logger.exception("MediaPipe hand model release failed")
