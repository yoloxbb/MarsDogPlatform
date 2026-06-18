"""轻量行为树基础节点。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class BehaviorNodeStatus(str, Enum):
    """行为树节点执行状态。"""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


@dataclass
class BehaviorTreeContext:
    """行为树运行上下文。"""

    blackboard: dict[str, object] = field(default_factory=dict)
    currentConcreteAction: str | None = None
    completedConcreteAction: str | None = None
    finishedConcreteActions: list[str] = field(default_factory=list)

    def SetBlackboardValue(self, key: str, value: object) -> None:
        """写入黑板数据。"""
        self.blackboard[key] = value

    def GetBlackboardValue(self, key: str, default: object | None = None) -> object | None:
        """读取黑板数据。"""
        return self.blackboard.get(key, default)


class BehaviorNode:
    """行为树节点基类。"""

    def __init__(self, name: str) -> None:
        """初始化节点名称。"""
        self.name = name

    def Tick(self, context: BehaviorTreeContext) -> BehaviorNodeStatus:
        """执行节点逻辑。"""
        raise NotImplementedError

    def Reset(self) -> None:
        """重置节点运行态。"""


class ConditionNode(BehaviorNode):
    """条件判断节点。"""

    def __init__(self, name: str, condition: Callable[[BehaviorTreeContext], bool]) -> None:
        """初始化条件节点。"""
        super().__init__(name)
        self.condition = condition

    def Tick(self, context: BehaviorTreeContext) -> BehaviorNodeStatus:
        """执行条件判断。"""
        return BehaviorNodeStatus.SUCCESS if self.condition(context) else BehaviorNodeStatus.FAILURE


class ActionNode(BehaviorNode):
    """具体动作节点。"""

    def __init__(self, actionName: str) -> None:
        """初始化具体动作节点。"""
        super().__init__(actionName)
        self.actionName = actionName
        self._started = False

    def Tick(self, context: BehaviorTreeContext) -> BehaviorNodeStatus:
        """执行具体动作节点。"""
        if not self._started:
            self._started = True
            context.currentConcreteAction = self.actionName
            return BehaviorNodeStatus.RUNNING

        if context.completedConcreteAction == self.actionName:
            context.finishedConcreteActions.append(self.actionName)
            context.completedConcreteAction = None
            context.currentConcreteAction = None
            return BehaviorNodeStatus.SUCCESS

        context.currentConcreteAction = self.actionName
        return BehaviorNodeStatus.RUNNING

    def Reset(self) -> None:
        """重置具体动作节点。"""
        self._started = False


class SequenceNode(BehaviorNode):
    """顺序执行节点。"""

    def __init__(self, name: str, children: list[BehaviorNode]) -> None:
        """初始化顺序执行节点。"""
        super().__init__(name)
        self.children = children
        self._currentIndex = 0

    def Tick(self, context: BehaviorTreeContext) -> BehaviorNodeStatus:
        """按顺序执行子节点。"""
        while self._currentIndex < len(self.children):
            status = self.children[self._currentIndex].Tick(context)
            if status == BehaviorNodeStatus.SUCCESS:
                self._currentIndex += 1
                continue
            if status == BehaviorNodeStatus.FAILURE:
                return BehaviorNodeStatus.FAILURE
            return BehaviorNodeStatus.RUNNING
        return BehaviorNodeStatus.SUCCESS

    def Reset(self) -> None:
        """重置顺序节点和所有子节点。"""
        self._currentIndex = 0
        for child in self.children:
            child.Reset()


class SelectorNode(BehaviorNode):
    """选择执行节点。"""

    def __init__(self, name: str, children: list[BehaviorNode]) -> None:
        """初始化选择节点。"""
        super().__init__(name)
        self.children = children
        self._currentIndex = 0

    def Tick(self, context: BehaviorTreeContext) -> BehaviorNodeStatus:
        """按顺序选择第一个可执行子节点。"""
        while self._currentIndex < len(self.children):
            status = self.children[self._currentIndex].Tick(context)
            if status == BehaviorNodeStatus.FAILURE:
                self.children[self._currentIndex].Reset()
                self._currentIndex += 1
                continue
            return status
        return BehaviorNodeStatus.FAILURE

    def Reset(self) -> None:
        """重置选择节点和所有子节点。"""
        self._currentIndex = 0
        for child in self.children:
            child.Reset()


class BehaviorTreeRunner:
    """行为树运行器。"""

    def __init__(self, actionType: str, root: BehaviorNode) -> None:
        """初始化行为树运行器。"""
        self.actionType = actionType
        self.root = root
        self.context = BehaviorTreeContext()
        self.status = BehaviorNodeStatus.RUNNING

    def Tick(self) -> BehaviorNodeStatus:
        """执行一次行为树 Tick。"""
        if self.status in {BehaviorNodeStatus.SUCCESS, BehaviorNodeStatus.FAILURE}:
            return self.status
        self.status = self.root.Tick(self.context)
        if self.status in {BehaviorNodeStatus.SUCCESS, BehaviorNodeStatus.FAILURE}:
            self.context.currentConcreteAction = None
        return self.status

    def MarkCurrentActionDone(self) -> bool:
        """标记当前具体动作已完成。"""
        if self.context.currentConcreteAction is None:
            return False
        self.context.completedConcreteAction = self.context.currentConcreteAction
        return True

    def GetCurrentConcreteAction(self) -> str:
        """获取当前正在执行的具体动作。"""
        return self.context.currentConcreteAction or ""

    def GetFinishedConcreteActions(self) -> list[str]:
        """获取已完成的具体动作列表。"""
        return list(self.context.finishedConcreteActions)

    def IsFinished(self) -> bool:
        """判断行为树是否已经结束。"""
        return self.status in {BehaviorNodeStatus.SUCCESS, BehaviorNodeStatus.FAILURE}

    def Reset(self) -> None:
        """重置行为树运行器。"""
        self.root.Reset()
        self.context = BehaviorTreeContext()
        self.status = BehaviorNodeStatus.RUNNING

    def Interrupt(self) -> None:
        """中断当前行为树。"""
        self.root.Reset()
        self.context.currentConcreteAction = None
        self.context.completedConcreteAction = None
        self.status = BehaviorNodeStatus.FAILURE
