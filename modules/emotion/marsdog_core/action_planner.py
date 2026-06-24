"""顶层行为到具体动作序列的规划器。"""

from __future__ import annotations

import random
from typing import Any

from .behavior_tree import ActionNode, BehaviorTreeRunner, ConditionNode, SelectorNode, SequenceNode
from .rules import IsConditionMatched
from .state import MarsdogState
from .types import NormalizeActionType


class ActionPlanner:
    """根据当前状态展开具体 ACT_* 动作。"""

    def __init__(
        self,
        state: MarsdogState,
        configs: dict[str, Any],
        randomGenerator: random.Random | None = None,
    ) -> None:
        """初始化动作规划器。"""
        self.state = state
        self.configs = configs
        self.random = randomGenerator or random.Random()

    def GetConcreteActions(self, actionType: object) -> list[str]:
        """获取顶层行为对应的具体动作序列。"""
        action = NormalizeActionType(actionType)
        plans = self.configs.get("actions", {}).get(action, [])
        for plan in plans:
            condition = plan.get("condition")
            if condition is None or self._IsConditionMatched(condition):
                return self._FlattenSteps(plan)
        return [action]

    def GetCurrentConcreteActions(self) -> list[str]:
        """获取当前顶层行为对应的具体动作序列。"""
        return self.GetConcreteActions(self.state.currentAction)

    def BuildBehaviorTree(self, actionType: object) -> BehaviorTreeRunner:
        """根据配置构建指定顶层行为的行为树。"""
        action = NormalizeActionType(actionType)
        plans = self.configs.get("actions", {}).get(action, [])
        if not plans:
            return BehaviorTreeRunner(action, ActionNode(action))

        planNodes = []
        for plan in plans:
            planNodes.append(self._BuildPlanNode(plan))
        return BehaviorTreeRunner(action, SelectorNode(f"{action}_SELECTOR", planNodes))

    def _IsConditionMatched(self, condition: dict[str, Any]) -> bool:
        """判断动作规划条件是否满足。"""
        if "all" in condition:
            return all(self._IsConditionMatched(item) for item in condition["all"])
        if "any" in condition:
            return any(self._IsConditionMatched(item) for item in condition["any"])
        if "demand" in condition:
            value = self.state.demands.get(condition["demand"], 0)
        elif "emotion" in condition:
            value = self.state.emotions.get(condition["emotion"], 0)
        elif "context" in condition:
            value = getattr(self.state, str(condition["context"]), None)
            return self._IsContextConditionMatched(value, condition)
        else:
            return True
        return IsConditionMatched(value, condition["operator"], float(condition["threshold"]))

    def _IsContextConditionMatched(self, actualValue: object, condition: dict[str, Any]) -> bool:
        """判断字符串或布尔类型的行为上下文条件。"""
        operator = str(condition.get("operator", "eq"))
        expectedValue = condition.get("value")
        if operator == "eq":
            return actualValue == expectedValue
        if operator == "neq":
            return actualValue != expectedValue
        try:
            return IsConditionMatched(
                float(actualValue),
                operator,
                float(condition.get("threshold", expectedValue)),
            )
        except (TypeError, ValueError):
            return False

    def _FlattenSteps(self, plan: dict[str, Any]) -> list[str]:
        """把分阶段动作配置展开为线性动作序列。"""
        if "steps" in plan:
            return list(plan["steps"])

        if "randomStepsByPhase" in plan:
            return self._BuildRandomStepList(plan)

        stepsByPhase = plan.get("stepsByPhase", {})
        orderedSteps: list[str] = []
        for phase in self._GetPhaseOrder(plan, stepsByPhase):
            orderedSteps.extend(stepsByPhase.get(phase, []))
        return orderedSteps

    def _BuildPlanNode(self, plan: dict[str, Any]) -> SequenceNode:
        """把单个动作规划配置转换为行为树节点。"""
        children = []
        condition = plan.get("condition")
        if condition is not None:
            children.append(
                ConditionNode(
                    f"{plan.get('name', 'ActionPlan')}_CONDITION",
                    lambda context, condition=condition: self._IsConditionMatched(condition),
                )
            )
        children.extend(self._BuildStepNodes(plan))
        return SequenceNode(plan.get("name", "ActionPlan"), children)

    def _BuildStepNodes(self, plan: dict[str, Any]) -> list[ActionNode | SequenceNode]:
        """把配置中的具体动作转换为行为树动作节点。"""
        if "steps" in plan:
            return [ActionNode(step) for step in plan["steps"]]

        if "randomStepsByPhase" in plan:
            return [ActionNode(step) for step in self._BuildRandomStepList(plan)]

        stepsByPhase = plan.get("stepsByPhase", {})
        phaseNodes: list[SequenceNode] = []
        for phase in self._GetPhaseOrder(plan, stepsByPhase):
            if phase in stepsByPhase:
                phaseNodes.append(self._BuildPhaseNode(phase, stepsByPhase[phase]))
        return phaseNodes

    def _BuildPhaseNode(self, phase: str, steps: list[str]) -> SequenceNode:
        """构建动作阶段节点。"""
        return SequenceNode(phase, [ActionNode(step) for step in steps])

    def _BuildRandomStepList(self, plan: dict[str, Any]) -> list[str]:
        """按配置从各阶段动作池随机抽取动作。"""
        orderedSteps = list(plan.get("fixedSteps", []))
        randomStepsByPhase = plan.get("randomStepsByPhase", {})
        randomSelection = plan.get("randomSelection", {})

        for phase in self._GetPhaseOrder(plan, randomStepsByPhase):
            phaseSteps = randomStepsByPhase.get(phase, [])
            count = int(randomSelection.get(phase, {}).get("count", 1))
            orderedSteps.extend(self._SamplePhaseSteps(phaseSteps, count))
        return orderedSteps

    def _SamplePhaseSteps(self, phaseSteps: list[str], count: int) -> list[str]:
        """从某个阶段动作池中随机抽取指定数量动作。"""
        if not phaseSteps or count <= 0:
            return []
        if count >= len(phaseSteps):
            return list(phaseSteps)
        return self.random.sample(phaseSteps, count)

    def _GetPhaseOrder(self, plan: dict[str, Any], stepsByPhase: dict[str, list[str]]) -> list[str]:
        """获取动作阶段执行顺序。"""
        if "phaseOrder" in plan:
            return list(plan["phaseOrder"])
        return list(stepsByPhase.keys())
