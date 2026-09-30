"""VoiceTask JSON envelope; generated service identity stays in the ROS shell."""
from __future__ import annotations
import json
from typing import Any


def handle_task(self, request: Any, response: Any, *, clock):
    started = clock()
    response.task_id = request.task_id
    response.task_type = request.task_type
    response.success = False
    response.result_json = ""
    response.error_message = ""
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
    response.latency_ms = (clock() - started) * 1000
    response_payload = (
        json.loads(response.result_json) if response.result_json else {}
    )
    self._trace(
        "service_complete",
        result="success" if response.success else "failure",
        service=str(
            self._config.get("topics", {}).get(
                "voice_task",
                "/perception/voice/task",
            )
        ),
        task_id=str(request.task_id),
        task_type=str(request.task_type),
        interaction_id=str(
            response_payload.get("interaction_id", self._interaction_id)
        ),
        latency_ms=round(response.latency_ms, 2),
        error=response.error_message,
        task_result=response_payload,
    )
    return response
