"""Simple behavior tree base classes.

Implements a minimal but complete behavior tree runtime:
- Status enum
- Node (base)
- Sequence (all children must succeed)
- Selector (first successful child wins)
"""

from __future__ import annotations

import time
from enum import Enum
from abc import ABC, abstractmethod
from typing import Optional, Any

try:
    from rich.console import Console
except ImportError:  # pragma: no cover
    Console = None  # type: ignore


class Status(Enum):
    """Behavior tree node status."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


class Node(ABC):
    """Base class for all behavior tree nodes."""

    def __init__(self, name: str):
        self.name = name
        self.status: Status = Status.FAILURE
        self._initialised = False
        self.console: Optional[Console] = None

    def setup(self, console: Optional[Console] = None) -> None:
        """One-time setup before first tick."""
        self.console = console

    def initialise(self) -> None:
        """Called once when this node becomes active (before first update)."""
        self._initialised = True

    @abstractmethod
    def update(self) -> Status:
        """Execute one tick of this node. Must return a Status."""
        ...

    def terminate(self, new_status: Status) -> None:
        """Called when the node is no longer active."""
        self.status = new_status
        self._initialised = False

    def tick(self) -> Status:
        """Public tick entry point. Handles initialise/update/terminate lifecycle."""
        if not self._initialised:
            self.initialise()

        new_status = self.update()

        if new_status != Status.RUNNING:
            self.terminate(new_status)
        else:
            self.status = Status.RUNNING

        return new_status

    def reset(self) -> None:
        """Reset this node's state."""
        self.status = Status.FAILURE
        self._initialised = False

    def log(self, message: str) -> None:
        """Log a message via the unified logger."""
        from .logger import get_logger
        get_logger("bt").info(f"[{self.name}] {message}")


class Sequence(Node):
    """Sequence composite: ticks children in order.

    - If a child FAILUREs → Sequence FAILUREs.
    - If a child RUNNINGs → Sequence returns RUNNING (resumes that child next tick).
    - If all children SUCCESS → Sequence SUCCESS.
    """

    def __init__(self, name: str, children: Optional[list[Node]] = None):
        super().__init__(name)
        self.children: list[Node] = children or []
        self._current_idx: int = 0

    def setup(self, console: Optional[Console] = None) -> None:
        super().setup(console)
        for child in self.children:
            child.setup(console)

    def initialise(self) -> None:
        super().initialise()
        self._current_idx = 0

    def update(self) -> Status:
        while self._current_idx < len(self.children):
            child = self.children[self._current_idx]
            child_status = child.tick()

            if child_status == Status.FAILURE:
                return Status.FAILURE
            elif child_status == Status.RUNNING:
                return Status.RUNNING
            else:
                # SUCCESS — move to next child
                self._current_idx += 1

        return Status.SUCCESS

    def terminate(self, new_status: Status) -> None:
        super().terminate(new_status)
        # Halt any running child
        if self._current_idx < len(self.children):
            child = self.children[self._current_idx]
            if child.status == Status.RUNNING:
                child.terminate(new_status)

    def reset(self) -> None:
        super().reset()
        self._current_idx = 0
        for child in self.children:
            child.reset()

    def add_child(self, child: Node) -> None:
        self.children.append(child)


class Selector(Node):
    """Selector composite (fallback): ticks children in order.

    - If a child SUCCESS → Selector SUCCESS.
    - If a child RUNNING → Selector returns RUNNING.
    - If all children FAILURE → Selector FAILURE.

    When memory=False, the selector re-evaluates from the first child each tick
    (it calls reset() on itself each tick before iterating). This is the default
    mode used for the root selector to implement priority-based preemption.
    """

    def __init__(self, name: str, children: Optional[list[Node]] = None, memory: bool = False):
        super().__init__(name)
        self.children: list[Node] = children or []
        self._current_idx: int = 0
        self._memory = memory

    def setup(self, console: Optional[Console] = None) -> None:
        super().setup(console)
        for child in self.children:
            child.setup(console)

    def initialise(self) -> None:
        super().initialise()
        if not self._memory:
            self._current_idx = 0

    def update(self) -> Status:
        while self._current_idx < len(self.children):
            child = self.children[self._current_idx]
            child_status = child.tick()

            if child_status == Status.SUCCESS:
                return Status.SUCCESS
            elif child_status == Status.RUNNING:
                return Status.RUNNING
            else:
                # FAILURE — try next child
                self._current_idx += 1

        return Status.FAILURE

    def terminate(self, new_status: Status) -> None:
        super().terminate(new_status)
        if self._current_idx < len(self.children):
            child = self.children[self._current_idx]
            if child.status == Status.RUNNING:
                child.terminate(new_status)

    def reset(self) -> None:
        super().reset()
        self._current_idx = 0
        for child in self.children:
            child.reset()

    def add_child(self, child: Node) -> None:
        self.children.append(child)
