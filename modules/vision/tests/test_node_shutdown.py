"""A signal may close the context before the executor creates its next wait set."""
from unittest.mock import Mock

import pytest
from rclpy._rclpy_pybind11 import RCLError
from rclpy.executors import ExternalShutdownException

from marsdog_vision_interaction.nodes import vision_interaction_node as entry

WAIT_SET_CLOSED = (
    "failed to initialize wait set: the given context is not valid, either "
    "rcl_init() was not called or rcl_shutdown() was called., at ./src/rcl/wait.c:130"
)


@pytest.mark.parametrize(
    "context_ok,error,expected",
    [
        (False, RCLError(WAIT_SET_CLOSED), None),
        (True, RCLError(WAIT_SET_CLOSED), RCLError),
        (False, RCLError("publisher failed"), RCLError),
        (True, RCLError("publisher failed"), RCLError),
        (False, RuntimeError("callback failed"), RuntimeError),
        (True, RuntimeError("callback failed"), RuntimeError),
        (False, ExternalShutdownException(), None),
        (True, KeyboardInterrupt(), None),
    ],
)
def test_shutdown_only_accepts_closed_context_wait_set(monkeypatch, context_ok, error, expected):
    node = Mock()
    executor = Mock()
    executor.spin.side_effect = error
    init = Mock()
    shutdown = Mock()
    monkeypatch.setattr(entry, "VisionInteractionNode", Mock(return_value=node))
    monkeypatch.setattr(entry, "MultiThreadedExecutor", Mock(return_value=executor))
    monkeypatch.setattr(entry.rclpy, "init", init)
    monkeypatch.setattr(entry.rclpy, "ok", Mock(return_value=context_ok))
    monkeypatch.setattr(entry.rclpy, "shutdown", shutdown)
    if expected:
        with pytest.raises(expected) as caught:
            entry.main(args=[])
        assert caught.value is error
    else:
        entry.main(args=[])
    init.assert_called_once_with(args=[])
    executor.shutdown.assert_called_once_with(timeout_sec=2.0)
    node.destroy_node.assert_called_once_with()
    shutdown.assert_called_once_with()
