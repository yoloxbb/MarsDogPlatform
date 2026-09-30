"""VisionTask JSON envelope; generated service identity stays in the ROS shell."""
from __future__ import annotations
import json
from typing import Any


def handle_task(self, request: Any, response: Any, *, clock, trace):
    started = clock()
    response.task_id = request.task_id
    response.task_type = request.task_type
    response.success = False
    response.result_json = ""
    response.error_message = ""
    trace(
        "stage_start",
        result="started",
        node="vision_interaction",
        module="vision_task",
        stage="service",
        task_id=str(request.task_id),
        task_type=str(request.task_type),
    )
    try:
        params = json.loads(request.params_json or "{}")
        if isinstance(params, list):
            params = {
                str(item.get("key", "")): item.get("value")
                for item in params if isinstance(item, dict)
            }
        if not isinstance(params, dict):
            params = {}
        result = self._run_task(str(request.task_type), params)
        response.success = bool(result.get("ok", True))
        response.result_json = json.dumps(result, ensure_ascii=False)
        if not response.success:
            response.error_message = str(result.get("error", "task failed"))
    except Exception as exc:
        response.error_message = str(exc)
    response.latency_ms = (clock() - started) * 1000.0
    trace(
        "stage_complete",
        result="success" if response.success else "failure",
        node="vision_interaction",
        module="vision_task",
        stage="service",
        task_id=str(response.task_id),
        task_type=str(response.task_type),
        latency_ms=round(float(response.latency_ms), 3),
        reason_code="" if response.success else "task_failed",
        error=str(response.error_message),
    )
    return response
