"""ROS2 性格参数节点。"""

from __future__ import annotations

import json
from typing import Any

from marsdog_core.personality_system import MarsdogPersonalitySystem
from marsdog_core.types import NormalizePersonalityProfileType, PersonalityParam, PersonalityProfileType

try:
    import rclpy
    from rcl_interfaces.msg import SetParametersResult
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    SetParametersResult = None
    ExternalShutdownException = None
    Node = object
    Parameter = None
    QoSProfile = None
    DurabilityPolicy = None
    HistoryPolicy = None
    ReliabilityPolicy = None
    String = None


class PersonalityNode(Node):
    """维护性格参数并发布性格状态。"""

    def __init__(self) -> None:
        """初始化性格 ROS2 节点。"""
        if rclpy is None or String is None or SetParametersResult is None:
            raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

        super().__init__("personality_node")
        self.system = MarsdogPersonalitySystem()
        self._syncingParameters = False
        self._pendingParameterSync = False

        self._DeclarePersonalityParameters()
        self.statePublisher = self.create_publisher(String, "/personality/state", _ReliableTransientLocalQoS(1))
        self.add_on_set_parameters_callback(self.OnSetParameters)
        self.create_timer(0.2, self.SyncRosParametersIfNeeded)
        self.PublishState()

    def OnSetParameters(self, parameters: list[object]):
        """处理 ROS2 参数服务写入。"""
        if self._syncingParameters:
            return SetParametersResult(successful=True)

        result = self._BuildNextPersonalityState(parameters)
        if not result["accepted"]:
            return SetParametersResult(successful=False, reason=result["reason"])

        if result["changed"]:
            self.system.SetPersonalityStateValue({"profile": result["profile"], "params": result["params"]})
            self._pendingParameterSync = True
            self.PublishState()
        return SetParametersResult(successful=True)

    def SyncRosParametersIfNeeded(self) -> None:
        """把 ROS2 参数值同步为核心系统的最终状态。"""
        if not self._pendingParameterSync:
            return
        state = self.system.GetPersonalityStateValue()
        params = state["params"]
        self._syncingParameters = True
        try:
            self.set_parameters(
                [
                    Parameter("profile", Parameter.Type.STRING, state["profile"]),
                    Parameter("A", Parameter.Type.INTEGER, int(params["A"])),
                    Parameter("O", Parameter.Type.INTEGER, int(params["O"])),
                    Parameter("E", Parameter.Type.INTEGER, int(params["E"])),
                    Parameter("C", Parameter.Type.INTEGER, int(params["C"])),
                ]
            )
        finally:
            self._syncingParameters = False
            self._pendingParameterSync = False

    def PublishState(self) -> None:
        """发布当前性格状态。"""
        message = String()
        message.data = json.dumps(self.system.GetPersonalityStateValue(), ensure_ascii=False)
        self.statePublisher.publish(message)

    def _DeclarePersonalityParameters(self) -> None:
        """声明 profile 与 A/O/E/C 参数。"""
        params = self.system.GetAllPersonalityParams()
        self.declare_parameter("profile", self.system.GetPersonalityProfileValue())
        for param in PersonalityParam:
            self.declare_parameter(param.value, int(params[param.value]))

    def _BuildNextPersonalityState(self, parameters: list[object]) -> dict[str, Any]:
        """根据一次参数写入构造下一份性格状态。"""
        currentProfile = self.system.GetPersonalityProfileValue()
        currentParams = self.system.GetAllPersonalityParams()
        requestedProfile = None
        requestedParams: dict[str, int] = {}

        for parameter in parameters:
            name = getattr(parameter, "name", "")
            value = getattr(parameter, "value", None)
            if name == "profile":
                try:
                    requestedProfile = NormalizePersonalityProfileType(value)
                except (TypeError, ValueError):
                    return self._Rejected(f"Unknown personality profile: {value}")
            elif name in {"A", "O", "E", "C"}:
                try:
                    requestedParams[name] = self._NormalizePersonalityParamInput(value)
                except (TypeError, ValueError):
                    return self._Rejected(f"Personality param {name} must be an integer in 0-100")

        if requestedProfile and requestedProfile != PersonalityProfileType.CUSTOM.value and requestedParams:
            return self._Rejected("Do not set a preset profile and custom A/O/E/C in the same request")

        nextProfile = currentProfile
        nextParams = dict(currentParams)
        if requestedProfile:
            nextProfile = requestedProfile
            if requestedProfile != PersonalityProfileType.CUSTOM.value:
                presetParams = self._GetPresetParams(requestedProfile)
                if presetParams is None:
                    return self._Rejected(f"Personality profile has no config: {requestedProfile}")
                nextParams = presetParams

        if requestedParams:
            nextProfile = PersonalityProfileType.CUSTOM.value
            nextParams.update(requestedParams)

        return {
            "accepted": True,
            "changed": requestedProfile is not None or bool(requestedParams),
            "profile": nextProfile,
            "params": nextParams,
            "reason": "",
        }

    def _GetPresetParams(self, profile: str) -> dict[str, int] | None:
        """读取预设性格的 A/O/E/C 参数。"""
        profileConfig = self.system.configs.get("personalityProfiles", {}).get(profile)
        if not profileConfig:
            return None
        params = profileConfig.get("params", {})
        if not isinstance(params, dict):
            return None
        normalized: dict[str, int] = {}
        for param in PersonalityParam:
            try:
                normalized[param.value] = self._NormalizePersonalityParamInput(params[param.value])
            except (KeyError, TypeError, ValueError):
                return None
        return normalized

    def _NormalizePersonalityParamInput(self, value: object) -> int:
        """校验 ROS2 参数里的 A/O/E/C 数值。"""
        if isinstance(value, bool):
            raise ValueError("bool is not accepted")
        normalized = int(value)
        if normalized < 0 or normalized > 100:
            raise ValueError("value out of range")
        return normalized

    def _Rejected(self, reason: str) -> dict[str, Any]:
        """构造参数拒绝结果。"""
        return {
            "accepted": False,
            "changed": False,
            "profile": self.system.GetPersonalityProfileValue(),
            "params": self.system.GetAllPersonalityParams(),
            "reason": reason,
        }


def _ReliableTransientLocalQoS(depth: int):
    """创建 RELIABLE + TRANSIENT_LOCAL QoS。"""
    if QoSProfile is None:
        return depth
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


def main(args=None) -> None:
    """启动性格参数节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = PersonalityNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
