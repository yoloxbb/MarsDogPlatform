"""ROS2 情绪计算节点。"""

from __future__ import annotations

import json
import time
from datetime import datetime

from marsdog_core import (
    MarsdogTimeController,
    RealTimeTickScheduler,
    VirtualTickScheduler,
)
from marsdog_core.emotion_system import MarsdogEmotionSystem
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


class EmotionEngineNode(Node):
    """发布情绪状态和表达阈值触发信号。"""

    def __init__(self) -> None:
        """初始化情绪 ROS2 节点。"""
        if rclpy is None or String is None:
            raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

        super().__init__("emotion_engine_node")
        self._DeclareTimeParameters()
        timeScale = self.get_parameter("time_scale").value
        virtualStartTime = self.get_parameter("virtual_start_time").value
        randomSeed = self.get_parameter("random_seed").value

        self.timeController = MarsdogTimeController(timeScale, virtualStartTime)
        self.system = MarsdogEmotionSystem(
            randomGenerator=GetRandomGeneratorValue(randomSeed),
        )
        virtualStartDateTime = self.timeController.GetVirtualStartDateTimeValue()
        self.emotionTickScheduler = VirtualTickScheduler(virtualStartDateTime, 1.0)
        self.emotionDecayScheduler = RealTimeTickScheduler(time.monotonic(), 1.0)
        self._timeSynchronized = False

        self.statePublisher = self.create_publisher(String, "/emotion/state", 10)
        self.signalPublisher = self.create_publisher(String, "/emotion/signal_event", 10)
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
        self.emotionDecayTimer = self.create_timer(
            1.0,
            self.OnEmotionDecayTimer,
        )
        self.get_logger().info(
            "Emotion time scale: %sx, virtual start: %s"
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
        """处理感知视觉情绪事件。"""
        ApplyVisualEventMessage(self.system, message)
        self.PublishSignalEvents()

    def OnAudioEventMessage(self, message) -> None:
        """处理感知声音情绪事件。"""
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
        if eventType == "TIME_TICK":
            self.Tick(virtualDateTime)
        elif eventType in {
            "TIME_TEST_STEP",
            "TIME_ACCELERATED_STEP",
        }:
            self.TickTestScenarioStep(virtualDateTime)

    def Tick(self, virtualNow: datetime | None = None) -> None:
        """按顺序发布每个到期虚拟秒对应的情绪状态。"""
        currentVirtualTime = virtualNow or self.timeController.GetVirtualDateTimeValue()
        for tickDateTime in self.emotionTickScheduler.GetDueTickDateTimesValue(currentVirtualTime):
            self.PublishState(tickDateTime)

    def OnEmotionDecayTimer(self) -> None:
        """按真实经过时间逐秒执行情绪自然衰减。"""
        dueTickCount = self.emotionDecayScheduler.GetDueTickCountValue(
            time.monotonic()
        )
        for _ in range(dueTickCount):
            # 延迟时逐真实秒补算，确保不会跳过中间情绪区间事件。
            self.system.ApplyEmotionDecay(1.0)
            self.PublishSignalEvents()

    def TickTestScenarioStep(self, virtualNow: datetime) -> None:
        """测试时间跳步时只发布当前状态，不回放中间虚拟秒。"""
        # 情绪衰减已经按真实时间计算，测试跳步无需生成大量中间状态。
        self.emotionTickScheduler.AlignToDateTimeValue(virtualNow)
        self.PublishState(virtualNow)

    def _InitializeTimeSynchronization(
        self,
        eventType: str,
        virtualStartDateTime: datetime,
        virtualDateTime: datetime,
    ) -> None:
        """首次接收权威时间时对齐情绪 Tick，不回放过量历史。"""
        self.emotionTickScheduler = VirtualTickScheduler(
            virtualStartDateTime,
            1.0,
        )
        if eventType != "TIME_INITIALIZED":
            self.emotionTickScheduler.AlignToDateTimeValue(
                virtualDateTime,
                includeCurrent=eventType == "TIME_TICK",
            )
        self._timeSynchronized = True

    def PublishState(self, virtualDateTime: datetime | None = None) -> None:
        """发布情绪状态。"""
        currentVirtualTime = virtualDateTime or self.timeController.GetVirtualDateTimeValue()
        payload = GetMessageWithTimeContextValue(
            self.system.GetEmotionStateValue(),
            self.timeController,
            currentVirtualTime,
        )
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.statePublisher.publish(message)

    def PublishSignalEvents(self, virtualDateTime: datetime | None = None) -> None:
        """发布情绪区间变化事件，未变化时不发布。"""
        currentVirtualTime = virtualDateTime or self.timeController.GetVirtualDateTimeValue()
        for signalEvent in self.system.GetEmotionSignalEventsValue():
            payload = GetMessageWithTimeContextValue(
                signalEvent,
                self.timeController,
                currentVirtualTime,
            )
            message = String()
            message.data = json.dumps(payload, ensure_ascii=False)
            self.signalPublisher.publish(message)


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
    """启动情绪计算节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = EmotionEngineNode()
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
