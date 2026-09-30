"""Shared Emotion/Needs publication mechanics; state authority stays in the core."""
from __future__ import annotations
import json
from typing import Any, Callable


def _PublishPayloadValue(payload, publisher, messageFactory) -> None:
    message = messageFactory()
    message.data = json.dumps(payload, ensure_ascii=False)
    publisher.publish(message)


def PublishStateValue(
    getStateValue: Callable[[], dict[str, Any]],
    timeController,
    publisher,
    messageFactory,
    withTimeContext,
    virtualDateTime=None,
):
    """Publish one snapshot and return its exact chosen virtual timestamp."""
    currentVirtualTime = virtualDateTime or timeController.GetVirtualDateTimeValue()
    payload = withTimeContext(getStateValue(), timeController, currentVirtualTime)
    _PublishPayloadValue(payload, publisher, messageFactory)
    return currentVirtualTime


def PublishSignalEventsValue(
    getSignalEventsValue: Callable[[], list[dict[str, Any]]],
    timeController,
    publisher,
    messageFactory,
    withTimeContext,
    virtualDateTime=None,
) -> None:
    """Choose one timestamp before obtaining and publishing the event sequence."""
    currentVirtualTime = virtualDateTime or timeController.GetVirtualDateTimeValue()
    for signalEvent in getSignalEventsValue():
        payload = withTimeContext(signalEvent, timeController, currentVirtualTime)
        _PublishPayloadValue(payload, publisher, messageFactory)
