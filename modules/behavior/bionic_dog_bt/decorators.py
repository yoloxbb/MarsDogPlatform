"""Behavior tree decorator nodes."""

from __future__ import annotations

import time
from .behavior_tree_node import Node, Status


class Inverter(Node):
    """Decorator that inverts child status: SUCCESS→FAILURE, FAILURE→SUCCESS."""

    def __init__(self, name: str, child: Node):
        super().__init__(name)
        self.child = child

    def setup(self, console=None) -> None:
        super().setup(console)
        self.child.setup(console)

    def update(self) -> Status:
        child_status = self.child.tick()
        if child_status == Status.SUCCESS:
            return Status.FAILURE
        elif child_status == Status.FAILURE:
            return Status.SUCCESS
        return Status.RUNNING

    def reset(self) -> None:
        super().reset()
        self.child.reset()


class CooldownDecorator(Node):
    """Decorator that prevents a behavior from running if it's in cooldown.

    Checks blackboard.cooldown_until before allowing the child to tick.
    """

    def __init__(self, name: str, child: Node, blackboard, behavior_name: str):
        super().__init__(name)
        self.child = child
        self.blackboard = blackboard
        self.behavior_name = behavior_name

    def setup(self, console=None) -> None:
        super().setup(console)
        self.child.setup(console)

    def update(self) -> Status:
        if self.blackboard.is_in_cooldown(self.behavior_name):
            return Status.FAILURE
        return self.child.tick()

    def reset(self) -> None:
        super().reset()
        self.child.reset()
