"""Pinned EmotiEffLib RK3588 facial expression backend."""

from __future__ import annotations

import hashlib
from pathlib import Path
import threading
from typing import Any

import numpy as np
from PIL import Image

from marsdog_vision_interaction.messages.facial_emotion import EMOTIONS
from marsdog_vision_interaction.utils.rknn_runtime import configure_rknn_runtime

PROFILE = "enet_b0_8_va_mtl"
MODEL_SHA256 = "e260bee2a207a14256db37d5b313bfa46d1f3fc344818ca3108a7d6fffcfd4f0"


def preprocess_face(crop: np.ndarray) -> np.ndarray:
    """Match the benchmark's BGR uint8 -> Pillow RGB bilinear -> NCHW."""
    if (not isinstance(crop, np.ndarray) or crop.dtype != np.uint8
            or crop.ndim != 3 or crop.shape[2] != 3 or not crop.size):
        raise ValueError("emotion input must be a nonempty BGR uint8 face crop")
    rgb = np.ascontiguousarray(crop[:, :, ::-1])
    resized = np.asarray(Image.fromarray(rgb).resize((224, 224), Image.Resampling.BILINEAR))
    array = resized.astype(np.float32) / np.float32(255.0)
    array = (array - np.asarray([.485, .456, .406], np.float32)) / np.asarray([.229, .224, .225], np.float32)
    return np.ascontiguousarray(array.transpose(2, 0, 1)[None])


def decode_expression(outputs: Any) -> dict[str, Any]:
    """Softmax only the eight expression logits; ignore valence/arousal."""
    if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
        raise ValueError("emotion model requires one output tensor")
    tensor = np.asarray(outputs[0])
    if tensor.shape != (1, 10) or tensor.dtype.kind != "f" or not np.isfinite(tensor).all():
        raise ValueError("emotion output must be finite floating point [1,10]")
    logits = tensor[0, :8].astype(np.float64)
    scores = np.exp(logits - logits.max())
    scores /= scores.sum()
    winner = int(scores.argmax())
    return {"emotion": EMOTIONS[winner], "intensity": float(scores[winner])}


class RknnEmotionBackend:
    """One validated runtime; close/inference are serialized and idempotent."""

    def __init__(self, model: str, *, profile: str = PROFILE,
                 core_mask: str = "auto", runtime_library: str = "") -> None:
        path = Path(model).expanduser()
        if profile != PROFILE:
            raise ValueError(f"unsupported emotion profile: {profile}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise ValueError(f"unverified emotion RKNN artifact: {path}")
        configure_rknn_runtime(runtime_library)
        from rknnlite.api import RKNNLite

        cores = {"auto": "NPU_CORE_AUTO", "0": "NPU_CORE_0", "1": "NPU_CORE_1",
                 "2": "NPU_CORE_2", "0_1": "NPU_CORE_0_1", "0_1_2": "NPU_CORE_0_1_2"}
        if isinstance(core_mask, bool) or str(core_mask) not in cores:
            raise ValueError(f"invalid emotion core_mask: {core_mask}")
        self._lock = threading.Lock()
        self._runtime: Any = RKNNLite()
        try:
            if self._runtime.load_rknn(str(path)) != 0:
                raise RuntimeError("emotion RKNN load failed")
            if self._runtime.init_runtime(core_mask=getattr(RKNNLite, cores[str(core_mask)])) != 0:
                raise RuntimeError("emotion RKNN runtime initialization failed")
        except Exception:
            self.close()
            raise

    def infer(self, crop: np.ndarray) -> dict[str, Any]:
        tensor = preprocess_face(crop)
        with self._lock:
            if self._runtime is None:
                raise RuntimeError("emotion backend is closed")
            return decode_expression(self._runtime.inference(inputs=[tensor], data_format=["nchw"]))

    def close(self) -> None:
        with self._lock:
            runtime, self._runtime = self._runtime, None
            if runtime is not None:
                runtime.release()
