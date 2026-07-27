"""ROS2 内部需求计算节点。"""

from __future__ import annotations

import json
from datetime import datetime

from marsdog_core import MarsdogTimeController, VirtualTickScheduler
from marsdog_core.need_system import MarsdogNeedSystem
from marsdog_ros2.behavior_result_adapter import ApplyBehaviorResultMessage
from marsdog_ros2.perception_adapter import ApplyAudioEventMessage, ApplyVisualEventMessage
from marsdog_ros2.personality_adapter import ApplyPersonalityStateMessage
from marsdog_ros2.time_context import GetMessageWithTimeContextValue, GetRandomGeneratorValue
from marsdog_ros2.time_state_adapter import (
    GetTimeContextDateTimeValue,
    GetTimeStateMessageValue,
)

try:
    import rclpy
    from rcl_interfaces.msg import ParameterDescriptor
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    ParameterDescriptor = None
    ExternalShutdownException = None
    Node = object
    QoSProfile = None
    ReliabilityPolicy = None
    HistoryPolicy = None
    DurabilityPolicy = None
    String = None


class InternalNeedNode(Node):
    """发布内部需求状态和阈值触发信号。"""

    def __init__(self) -> None:
        """初始化内部需求 ROS2 节点。"""
        if rclpy is None or String is None:
            raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

        super().__init__("internal_need_node")
        self._DeclareTimeParameters()
        timeScale = self.get_parameter("time_scale").value
        virtualStartTime = self.get_parameter("virtual_start_time").value
        randomSeed = self.get_parameter("random_seed").value

        self.timeController = MarsdogTimeController(timeScale, virtualStartTime)
        self.system = MarsdogNeedSystem(
            randomGenerator=GetRandomGeneratorValue(randomSeed),
        )
        virtualStartDateTime = self.timeController.GetVirtualStartDateTimeValue()
        self.demandTickScheduler = VirtualTickScheduler(virtualStartDateTime, 600.0)
        self._timeSynchronized = False
        if self._IsMorningStart(virtualStartDateTime):
            self.system.ResetDemandsToMorningInitialValues(virtualStartDateTime)

        self.statePublisher = self.create_publisher(String, "/internal_need/state", 10)
        self.signalPublisher = self.create_publisher(String, "/internal_need/signal_event", 10)
        self.create_subscription(String, "/perception/visual_event", self.OnVisualEventMessage, _BestEffortQoS(5))
        self.create_subscription(String, "/perception/audio_event", self.OnAudioEventMessage, _ReliableQoS(10))
        self.create_subscription(String, "/behavior/result_event", self.OnBehaviorResultMessage, _ReliableQoS(10))
        self.create_subscription(String, "/personality/state", self.OnPersonalityStateMessage, _ReliableTransientLocalQoS(1))
        self.create_subscription(
            String,
            "/simulation/time_state",
            self.OnTimeStateMessage,
            _ReliableTransientLocalQoS(1000),
        )
        self.create_timer(1.0, self.PublishState)
        self.get_logger().info(
            "Internal need time scale: %sx, virtual start: %s"
            % (
                self.timeController.GetTimeScaleValue(),
                virtualStartDateTime.isoformat(),
            )
        )

    def _DeclareTimeParameters(self) -> None:
        """声明仅允许启动时设置的时间测试参数。"""
        self.declare_parameter(
            "time_scale",
            1,
            descriptor=_ReadOnlyParameterDescriptor(
                "Virtual time scale: integer from 1 to 100"
            ),
        )
        self.declare_parameter(
            "virtual_start_time",
            "auto",
            descriptor=_ReadOnlyParameterDescriptor("Virtual start time: auto or HH:MM"),
        )
        self.declare_parameter(
            "random_seed",
            -1,
            descriptor=_ReadOnlyParameterDescriptor("Random seed: -1 or a non-negative integer"),
        )

    def OnVisualEventMessage(self, message) -> None:
        """处理感知视觉事件。"""
        ApplyVisualEventMessage(self.system, message)
        self.PublishSignalEvents()

    def OnAudioEventMessage(self, message) -> None:
        """处理感知声音事件。"""
        ApplyAudioEventMessage(self.system, message)
        self.PublishSignalEvents()

    def OnBehaviorResultMessage(self, message) -> None:
        """处理行为组回传的结果事件。"""
        ApplyBehaviorResultMessage(self.system, message)
        self.PublishSignalEvents()

    def OnPersonalityStateMessage(self, message) -> None:
        """同步性格参数状态。"""
        ApplyPersonalityStateMessage(self.system, message)

    def OnTimeStateMessage(self, message) -> None:
        """同步权威虚拟时间并消费逐虚拟秒 Tick。"""
        payload = GetTimeStateMessageValue(message)
        if not payload:
            return
        timeContext = payload["timeContext"]
        virtualDateTime = GetTimeContextDateTimeValue(payload, "virtualDateTime")
        virtualStartDateTime = GetTimeContextDateTimeValue(
            payload,
            "virtualStartDateTime",
        )
        if virtualDateTime is None or virtualStartDateTime is None:
            return

        try:
            self.timeController.SetTimeContextValue(timeContext)
        except (TypeError, ValueError) as error:
            self.get_logger().warning(f"Ignored invalid time state: {error}")
            return

        eventType = str(payload.get("event_type", ""))
        if not self._timeSynchronized:
            self._InitializeTimeSynchronization(
                eventType,
                virtualStartDateTime,
                virtualDateTime,
            )
        if eventType in {
            "TIME_TICK",
            "TIME_TEST_STEP",
            "TIME_ACCELERATED_STEP",
        }:
            self.UpdateDemandTick(virtualDateTime)

    def UpdateDemandTick(self, virtualNow: datetime | None = None) -> None:
        """按顺序补算所有到期的虚拟 10 分钟需求 Tick。"""
        currentVirtualTime = virtualNow or self.timeController.GetVirtualDateTimeValue()
        for tickDateTime in self.demandTickScheduler.GetDueTickDateTimesValue(currentVirtualTime):
            self.system.UpdateNaturalDemandsByTime(tickDateTime)
            self.PublishSignalEvents(tickDateTime)

    def _InitializeTimeSynchronization(
        self,
        eventType: str,
        virtualStartDateTime: datetime,
        virtualDateTime: datetime,
    ) -> None:
        """首次接收权威时间时对齐需求 Tick，不回放过量历史。"""
        self.demandTickScheduler = VirtualTickScheduler(
            virtualStartDateTime,
            600.0,
        )
        if eventType != "TIME_INITIALIZED":
            self.demandTickScheduler.AlignToDateTimeValue(
                virtualDateTime,
                includeCurrent=eventType
                in {
                    "TIME_TICK",
                    "TIME_TEST_STEP",
                    "TIME_ACCELERATED_STEP",
                },
            )
        if self._IsMorningStart(virtualStartDateTime):
            resetKey = self.system.GetMorningResetKey(virtualStartDateTime)
            if self.system.state.lastMorningResetKey != resetKey:
                self.system.ResetDemandsToMorningInitialValues(virtualStartDateTime)
        self._timeSynchronized = True

    def PublishState(self, virtualDateTime: datetime | None = None) -> None:
        """发布内部需求状态。"""
        currentVirtualTime = virtualDateTime or self.timeController.GetVirtualDateTimeValue()
        payload = GetMessageWithTimeContextValue(
            self.system.GetInternalNeedStateValue(),
            self.timeController,
            currentVirtualTime,
        )
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.statePublisher.publish(message)
        self.PublishSignalEvents(currentVirtualTime)

    def PublishSignalEvents(self, virtualDateTime: datetime | None = None) -> None:
        """发布需求等级变化事件，未变化时不发布。"""
        currentVirtualTime = virtualDateTime or self.timeController.GetVirtualDateTimeValue()
        for signalEvent in self.system.GetDemandSignalEventsValue():
            payload = GetMessageWithTimeContextValue(
                signalEvent,
                self.timeController,
                currentVirtualTime,
            )
            message = String()
            message.data = json.dumps(payload, ensure_ascii=False)
            self.signalPublisher.publish(message)

    def _IsMorningStart(self, startDateTime: datetime) -> bool:
        """判断虚拟起点是否为完整一天测试的 06:00。"""
        return (
            startDateTime.hour == 6
            and startDateTime.minute == 0
            and startDateTime.second == 0
        )


def _BestEffortQoS(depth: int):
    """创建 BEST_EFFORT QoS。"""
    if QoSProfile is None:
        return depth
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )


def _ReliableQoS(depth: int):
    """创建 RELIABLE QoS。"""
    if QoSProfile is None:
        return depth
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
    )


def _ReliableTransientLocalQoS(depth: int):
    """创建可接收最新保留状态的 RELIABLE + TRANSIENT_LOCAL QoS。"""
    if QoSProfile is None:
        return depth
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


def _ReadOnlyParameterDescriptor(description: str):
    """创建启动后不可动态修改的 ROS2 参数描述。"""
    if ParameterDescriptor is None:
        return None
    return ParameterDescriptor(description=description, read_only=True)


def main(args=None) -> None:
    """启动内部需求计算节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = InternalNeedNode()
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
