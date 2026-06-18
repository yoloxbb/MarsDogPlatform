"""事件接口实现。"""

from __future__ import annotations

from typing import Any

from .state import EventData


class EventAPI:
    """事件 API 混入类。"""

    def PostEvent(self, eventTag: str, metadata: dict[str, Any] | None = None) -> bool:
        """提交一个外部事件到事件队列。"""
        if not eventTag:
            return False
        event = EventData(str(eventTag), dict(metadata or {}))
        self.state.pendingEvents.append(event)
        for callback in list(self._eventHandlers.get(event.eventTag, [])):
            callback(event)
        return True

    def RegisterEventHandler(self, eventTag: str, callback) -> None:
        """注册指定事件的处理器。"""
        if not eventTag or not callable(callback):
            return
        self._eventHandlers.setdefault(str(eventTag), []).append(callback)

    def UnregisterEventHandler(self, eventTag: str, callback) -> None:
        """取消注册事件处理器。"""
        handlers = self._eventHandlers.get(str(eventTag), [])
        if callback in handlers:
            handlers.remove(callback)
