"""Non-blocking client for VoiceTask interaction hold leases."""

from __future__ import annotations

import json
import uuid
from typing import Callable

from .ros2_compat import HAS_ROS2, is_ros2_ready


class VoiceSessionClientAdapter:
    """Keep long wake engagement work inside the original voice session."""

    SERVICE_NAME = "/perception/voice/task"

    def __init__(self, node) -> None:
        self._node = node
        self._logger = node.get_logger()
        self._ros2_ready = bool(
            HAS_ROS2
            and is_ros2_ready()
            and getattr(node, "_ros2_ready", True)
        )
        self._client = None
        self._service_type = None
        if self._ros2_ready:
            self._setup_client()

    def _setup_client(self) -> None:
        candidates = (
            ("marsdog_voice_interaction.srv", "VoiceTask"),
            ("marsdog_interfaces.srv", "VoiceTask"),
        )
        for module_name, class_name in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                service_type = getattr(module, class_name)
                self._client = self._node.create_client(
                    service_type, self.SERVICE_NAME
                )
                self._service_type = service_type
                self._logger.info(
                    "Voice session service ready: %s (%s.%s)"
                    % (self.SERVICE_NAME, module_name, class_name)
                )
                return
            except Exception as exc:
                self._logger.debug(
                    "VoiceTask interface unavailable: %s.%s (%s)"
                    % (module_name, class_name, exc)
                )
        self._logger.warn(
            "VoiceTask interface unavailable; wake engagement cannot hold "
            "the voice idle timer"
        )

    def hold(
        self,
        interaction_id: str,
        hold_token: str,
        *,
        lease_sec: float,
        callback: Callable[[dict | None], None] | None = None,
    ) -> bool:
        return self._call(
            "hold_interaction",
            {
                "interaction_id": interaction_id,
                "hold_token": hold_token,
                "lease_sec": float(lease_sec),
                "reason": "wake_target_approach",
            },
            callback,
        )

    def release(
        self,
        interaction_id: str,
        hold_token: str,
        *,
        reset_idle_timer: bool,
        callback: Callable[[dict | None], None] | None = None,
    ) -> bool:
        return self._call(
            "release_interaction_hold",
            {
                "interaction_id": interaction_id,
                "hold_token": hold_token,
                "reset_idle_timer": bool(reset_idle_timer),
            },
            callback,
        )

    def _call(
        self,
        task_type: str,
        params: dict,
        callback: Callable[[dict | None], None] | None,
    ) -> bool:
        # Standalone tests do not own a Voice node.  Emulate the service result
        # while preserving the exact request semantics in the node state.
        if not self._ros2_ready:
            if callback is not None:
                callback({"ok": True, "mock": True, **params})
            return True

        client = self._client
        service_type = self._service_type
        if client is None or service_type is None:
            return False
        if hasattr(client, "service_is_ready") and not client.service_is_ready():
            self._logger.warn("Voice session service is not ready")
            return False

        request = service_type.Request()
        request.task_id = "bt_voice_%s" % uuid.uuid4().hex[:8]
        request.task_type = task_type
        request.params_json = json.dumps(params, ensure_ascii=False)
        try:
            future = client.call_async(request)
        except Exception as exc:
            self._logger.error("Voice session service call failed: %s" % exc)
            return False

        def _done(completed) -> None:
            result = None
            try:
                response = completed.result()
                if response is not None and bool(response.success):
                    parsed = json.loads(response.result_json or "{}")
                    if isinstance(parsed, dict):
                        result = parsed
                else:
                    self._logger.warn(
                        "Voice task %s rejected: %s"
                        % (
                            task_type,
                            getattr(response, "error_message", "empty response")
                            if response is not None else "empty response",
                        )
                    )
            except Exception as exc:
                self._logger.error(
                    "Voice task %s response failed: %s" % (task_type, exc)
                )
            if callback is not None:
                callback(result)

        future.add_done_callback(_done)
        return True
