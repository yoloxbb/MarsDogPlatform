"""ROS2 统一虚拟时间控制节点。"""

from __future__ import annotations

import json
import time
from datetime import datetime

from marsdog_core import MarsdogTimeController, VirtualTickScheduler
from marsdog_core.types import NormalizeTimeScaleValue

try:
    import rclpy
    from rcl_interfaces.msg import IntegerRange, ParameterDescriptor, SetParametersResult
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    IntegerRange = None
    ParameterDescriptor = None
    SetParametersResult = None
    ExternalShutdownException = None
    Node = object
    QoSProfile = None
    DurabilityPolicy = None
    HistoryPolicy = None
    ReliabilityPolicy = None
    String = None


class TimeControllerNode(Node):
    """维护权威虚拟时钟并发布逐虚拟秒 Tick。"""

    def __init__(self) -> None:
        """初始化统一时间控制节点。"""
        if rclpy is None or String is None or SetParametersResult is None:
            raise RuntimeError(
                "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
            )

        super().__init__("time_controller_node")
        self._DeclareTimeParameters()
        self.timeController = MarsdogTimeController(
            self.get_parameter("time_scale").value,
            self.get_parameter("virtual_start_time").value,
        )
        self.tickScheduler = VirtualTickScheduler(
            self.timeController.GetVirtualStartDateTimeValue(),
            1.0,
        )
        self.tickSequence = 0
        self.timeTimer = None
        self.statePublisher = self.create_publisher(
            String,
            "/simulation/time_state",
            _ReliableTransientLocalQoS(1000),
        )
        self.add_on_set_parameters_callback(self.OnSetParameters)
        self._ResetTimeTimer()
        self.PublishTimeState(
            "TIME_INITIALIZED",
            self.timeController.GetVirtualStartDateTimeValue(),
        )
        self._LogCurrentScale("initialized")

    def OnSetParameters(self, parameters: list[object]):
        """校验并应用运行时整数倍率切换。"""
        requestedScale = None
        for parameter in parameters:
            if getattr(parameter, "name", "") == "time_scale":
                requestedScale = getattr(parameter, "value", None)

        if requestedScale is None:
            return SetParametersResult(successful=True)

        try:
            normalizedScale = NormalizeTimeScaleValue(requestedScale)
        except (TypeError, ValueError):
            return SetParametersResult(
                successful=False,
                reason="time_scale must be an integer between 1 and 24",
            )

        if normalizedScale == self.timeController.GetTimeScaleValue():
            return SetParametersResult(successful=True)

        # 先消费旧倍率下已经到期的 Tick，再连续切换时间锚点。
        self.PublishDueTicks()
        self.timeController.SetTimeScaleValue(normalizedScale)
        self._ResetTimeTimer()
        self.PublishTimeState(
            "TIME_MODE_CHANGED",
            self.timeController.GetVirtualDateTimeValue(),
        )
        self._LogCurrentScale("changed")
        return SetParametersResult(successful=True)

    def PublishDueTicks(self) -> None:
        """发布截至当前虚拟时间全部到期的逐秒 Tick。"""
        virtualNow = self.timeController.GetVirtualDateTimeValue()
        for tickDateTime in self.tickScheduler.GetDueTickDateTimesValue(virtualNow):
            self.tickSequence += 1
            self.PublishTimeState("TIME_TICK", tickDateTime)

    def PublishTimeState(self, eventType: str, virtualDateTime: datetime) -> None:
        """发布权威时间状态或倍率变化事件。"""
        wallTimestamp = time.time()
        payload = {
            "schema_version": "1.0",
            "timestamp": wallTimestamp,
            "event_type": eventType,
            "tickSequence": self.tickSequence,
            "timeContext": self.timeController.GetTimeContextValue(
                virtualDateTime=virtualDateTime,
                wallTimestamp=wallTimestamp,
            ),
        }
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.statePublisher.publish(message)

    def _DeclareTimeParameters(self) -> None:
        """声明动态倍率参数和只读虚拟起点参数。"""
        self.declare_parameter(
            "time_scale",
            1,
            descriptor=_TimeScaleParameterDescriptor(readOnly=False),
        )
        self.declare_parameter(
            "virtual_start_time",
            "auto",
            descriptor=_ParameterDescriptor(
                "Virtual start time: auto or HH:MM",
                readOnly=True,
            ),
        )

    def _ResetTimeTimer(self) -> None:
        """按当前倍率重建逐虚拟秒定时器。"""
        if self.timeTimer is not None:
            self.destroy_timer(self.timeTimer)
        self.timeTimer = self.create_timer(
            self.timeController.GetRealIntervalValue(1.0),
            self.PublishDueTicks,
        )

    def _LogCurrentScale(self, operation: str) -> None:
        """记录当前时间倍率和连续虚拟时间。"""
        self.get_logger().info(
            "Time scale %s: %sx, virtual time: %s, revision: %s"
            % (
                operation,
                self.timeController.GetTimeScaleValue(),
                self.timeController.GetVirtualDateTimeValue().isoformat(),
                self.timeController.GetTimeRevisionValue(),
            )
        )


def _ParameterDescriptor(description: str, readOnly: bool):
    """创建 ROS2 参数描述。"""
    if ParameterDescriptor is None:
        return None
    return ParameterDescriptor(description=description, read_only=readOnly)


def _TimeScaleParameterDescriptor(readOnly: bool):
    """创建限制为 1-24 整数的 ROS2 倍率参数描述。"""
    if ParameterDescriptor is None or IntegerRange is None:
        return None
    return ParameterDescriptor(
        description="Virtual time scale: integer from 1 to 24",
        read_only=readOnly,
        integer_range=[IntegerRange(from_value=1, to_value=24, step=1)],
    )


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
    """启动统一虚拟时间控制节点。"""
    if rclpy is None:
        raise RuntimeError(
            "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
        )

    rclpy.init(args=args)
    node = TimeControllerNode()
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
