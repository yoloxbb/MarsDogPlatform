"""Vision task dispatch through the existing provider and target-query ports."""
from __future__ import annotations
import base64
from typing import Any


def run_task(self, task_type: str, params: dict[str, Any]):
    vision = self._providers.get("vision")
    if task_type == "check_person":
        if vision is None or not hasattr(vision, "check_person"):
            return {"ok": False, "error": "vision unavailable"}
        return {"ok": True, **vision.check_person()}  # type: ignore[attr-defined]
    if task_type == "query_targets":
        return self._query_targets(params)
    if task_type == "locate_person_once":
        return self._locate_person_once(params)
    if task_type == "detect_objects":
        return self._run_object_detection(
            params,
            source="service",
            wait_for_slot=True,
        )
    if task_type == "set_object_detection":
        return self._set_object_detection(params)
    if task_type == "get_object_detection_state":
        return {
            "ok": True,
            # `stream` remains the externally owned Action/debug session.
            # The automatic held-pose scheduler is observable separately
            # and must never make a downstream caller think its own session
            # is occupied.
            "stream": self._object_stream.snapshot(),
            "automatic_stream": self._held_object_stream.snapshot(),
        }
    if task_type == "recognize_face":
        recognizer = self._providers.get("face_recognition")
        if recognizer is None:
            return {"ok": False, "error": "face recognizer unavailable"}
        return {
            "ok": True,
            **recognizer.recognize(self._crop_largest_face()),  # type: ignore[attr-defined]
        }
    if task_type == "start_face_enrollment":
        with self._enrollment_lock:
            return self._enrollment.start_face(
                str(params.get("name", "")),
                params.get("required_shots"),
            )
    if task_type == "cancel_face_enrollment":
        with self._enrollment_lock:
            return self._enrollment.cancel_face()
    if task_type == "upload_face":
        payload = base64.b64decode(
            str(params.get("image_base64", "")), validate=True
        )
        with self._enrollment_lock:
            result = self._run_with_shared_face_models(
                lambda: self._enrollment.enroll_face_from_image(
                    str(params.get("name", "")), payload
                )
            )
            if result.get("ok"):
                self._sync_face_registry()
            return result
    if task_type == "list_face_records":
        with self._enrollment_lock:
            return self._enrollment.list_face_records()
    if task_type == "list_face_samples":
        with self._enrollment_lock:
            return self._enrollment.list_face_samples(
                str(params.get("name", ""))
            )
    if task_type == "get_face_sample":
        with self._enrollment_lock:
            return self._enrollment.get_face_sample(
                str(params.get("name", "")),
                int(params.get("sample_id", 0)),
            )
    if task_type == "replace_face_sample":
        payload = base64.b64decode(
            str(params.get("image_base64", "")), validate=True
        )
        with self._enrollment_lock:
            result = self._run_with_shared_face_models(
                lambda: self._enrollment.replace_face_sample(
                    str(params.get("name", "")),
                    int(params.get("sample_id", 0)),
                    payload,
                )
            )
            if result.get("ok"):
                self._sync_face_registry()
            return result
    if task_type == "delete_face_sample":
        with self._enrollment_lock:
            result = self._enrollment.delete_face_sample(
                str(params.get("name", "")),
                int(params.get("sample_id", 0)),
            )
            if result.get("ok"):
                self._sync_face_registry()
            return result
    if task_type == "list_faces":
        with self._enrollment_lock:
            return {
                "ok": True,
                "faces": self._enrollment.list_enrolled_faces(),
            }
    if task_type == "delete_face":
        with self._enrollment_lock:
            result = self._enrollment.delete_face(
                str(params.get("name", ""))
            )
            if result.get("ok"):
                self._sync_face_registry()
            return result
    return {"ok": False, "error": f"unsupported task_type: {task_type}"}
