"""Face recognition provider using SFace ONNX or RKNN model.

Lazy-loaded — model is only initialized on first enroll/recognize call.
Extracts 128-dim embeddings and matches via cosine similarity.

Triggered by:
  /perception/perception_task enroll_face    → extract + store embedding
  /perception/perception_task recognize_face → extract + search enrolled
  wakeup auto-recognition             → recognize largest face in observation
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from marsdog_vision_interaction.providers.base import BaseProvider
from marsdog_vision_interaction.providers.face_backends import create_face_recognizer
from marsdog_vision_interaction.utils.logging_utils import vision_timing_trace

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class FaceRecognitionProvider(BaseProvider):
    """Face recognition — SFace embedding extraction + matching.

    Lazy-loads model on first call. Thread-safe for embedding store.

    Attributes:
        _model_path: Path to SFace ONNX or RKNN model.
        _match_threshold: Cosine similarity threshold for match.
        _recognizer: OpenCV-compatible SFace feature adapter.
        _enrolled: Dict of user_id → embedding (np.ndarray 128-dim).
        _lock: Protects _enrolled.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        self._model_path = config.get("face_recogn_model", "")
        self._match_threshold = float(config.get("match_threshold", 0.5))

        self._recognizer: Any = None
        self._inference_lock = threading.RLock()
        self._stopped = False
        self.model_error: str | None = None
        self._loaded = False
        self._enrolled: dict[str, list[np.ndarray]] = {}
        self._lock = threading.Lock()

    @property
    def enrolled_count(self) -> int:
        with self._lock:
            return len(self._enrolled)

    # ── Lifecycle ──────────────────────────────────────────────

    def start(self) -> None:
        with self._inference_lock:
            self._stopped = False
            if self._loaded and self._recognizer is None:
                self.available = False
                return
        try:
            if not self._model_path:
                logger.info("FaceRecognitionProvider — no model path, lazy-load disabled")
                self.available = True  # Still available for enroll (in-memory)
            else:
                logger.info("FaceRecognitionProvider — lazy-load, model=%s", self._model_path)
                self.available = True
            logger.info("FaceRecognitionProvider started (lazy)")
        except Exception as exc:
            self.available = False
            logger.warning("FaceRecognitionProvider start failed: %s", exc, exc_info=True)

    def stop(self) -> None:
        with self._inference_lock:
            self._stopped = True
            self.available = False
            if self._recognizer is not None:
                try:
                    self._recognizer.close()
                except Exception:
                    logger.exception("SFace release failed")
            self._recognizer = None
            self._loaded = False
            self.model_error = None
            with self._lock:
                self._enrolled.clear()
        logger.info("FaceRecognitionProvider stopped")

    # ── Lazy model loading and embedding extraction ─────────────

    def _ensure_loaded(self) -> bool:
        """Called under the inference lock; never replace a failed model silently."""
        if self._stopped:
            return False
        if self._loaded:
            return self._recognizer is not None
        self._loaded = True
        if not self._model_path:
            self.model_error = "No face_recogn_model configured"
            logger.warning(self.model_error)
            return False
        try:
            self._recognizer = create_face_recognizer(
                self._model_path,
                rknn_config=self.config.get("face_recogn_rknn"),
                runtime_library=self.config.get("rknn_runtime_library", ""),
            )
            self.model_error = None
            logger.info("FaceRecognitionProvider — SFace loaded: %s", self._model_path)
            return True
        except Exception as exc:
            self.model_error = str(exc)
            self.available = False
            logger.error("FaceRecognitionProvider — SFace load failed: %s", exc)
            return False

    def _extract_embedding(self, face_roi: np.ndarray) -> np.ndarray | None:
        """Extract a 128-dimensional feature from a BGR crop.

        The adapter owns resize and model-specific preprocessing. In particular,
        do not apply mean/std here: the supported SFace graph already contains
        normalization, and observation uses this same adapter.
        """
        with self._inference_lock:
            if not self._ensure_loaded() or self._recognizer is None:
                return None
            try:
                embedding = self._recognizer.feature(face_roi)
                return embedding.reshape(-1).astype(np.float32)
            except Exception as exc:
                self.model_error = str(exc)
                fatal_error = getattr(self._recognizer, "fatal_error", None)
                if fatal_error:
                    self.model_error = str(fatal_error)
                    self.available = False
                    # The adapter has already released its runtime. Removing
                    # it prevents every later request from retrying a dead
                    # context while preserving the visible failure status.
                    self._recognizer = None
                logger.error("Face embedding extraction error: %s", exc, exc_info=True)
                return None

    # ── Public API ─────────────────────────────────────────────

    def enroll(self, face_roi: np.ndarray | None = None,
               user_id: str | None = None) -> dict[str, Any]:
        """Enroll a face with a user ID.

        Args:
            face_roi: BGR face image (cropped from observation).
            user_id: User label to associate with the embedding.

        Returns:
            Dict with success and user_id.
        """
        if face_roi is None:
            logger.warning("FaceRecognition enroll — no face ROI provided")
            return {"success": False, "user_id": user_id or "unknown"}

        sid = user_id or f"user_{len(self._enrolled) + 1:03d}"

        with self._inference_lock:
            if self._stopped:
                return {"success": False, "user_id": sid}
            embedding = self._extract_embedding(face_roi)
            if embedding is None:
                return {"success": False, "user_id": sid}
            with self._lock:
                self._enrolled.setdefault(sid, []).append(embedding)

        logger.info("FaceRecognition enrolled: id=%s, total=%d", sid, len(self._enrolled))
        return {"success": True, "user_id": sid}

    def recognize(self, face_roi: np.ndarray | None = None) -> dict[str, Any]:
        """Recognize a face against enrolled users.

        Args:
            face_roi: BGR face image (cropped from observation).

        Returns:
            Dict with user_id, confidence, and matched flag.
        """
        if face_roi is None:
            return {"user_id": "unknown", "confidence": 0.0, "matched": False}

        if not self._enrolled:
            return {"user_id": "unknown", "confidence": 0.0, "matched": False}

        started = time.perf_counter()
        result_status = "failure"
        reason_code = "embedding_unavailable"
        best_id = "unknown"
        best_score = 0.0
        matched = False
        try:
            embedding = self._extract_embedding(face_roi)
            if embedding is None:
                return {
                    "user_id": "unknown",
                    "confidence": 0.0,
                    "matched": False,
                }

            with self._lock:
                for uid, templates in self._enrolled.items():
                    for stored_emb in templates:
                        score = _cosine(embedding, stored_emb)
                        if score > best_score:
                            best_score = score
                            best_id = uid

            matched = best_score >= self._match_threshold
            result_status = "success"
            reason_code = "matched" if matched else "no_match"

            logger.info(
                "FaceRecognition recognized: id=%s score=%.3f matched=%s",
                best_id, best_score, matched,
            )

            return {
                "user_id": best_id if matched else "unknown",
                "confidence": round(float(best_score), 4),
                "matched": matched,
            }
        finally:
            vision_timing_trace(
                node="vision_interaction",
                module="face_recognition",
                stage="sface_task_recognize",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                result=result_status,
                force=True,
                identity=best_id if matched else "unknown",
                confidence=round(float(best_score), 4),
                reason_code=reason_code,
                template_identity_count=len(self._enrolled),
            )

    def clear_enrolled(self) -> None:
        """Drop the in-memory registry before rebuilding it from local storage."""
        with self._lock:
            self._enrolled.clear()
