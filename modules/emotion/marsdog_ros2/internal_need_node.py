"""ROS2 内部需求计算节点。"""

from __future__ import annotations

import json

from marsdog_core.need_system import MarsdogNeedSystem
from marsdog_ros2.behavior_result_adapter import ApplyBehaviorResultMessage
from marsdog_ros2.perception_adapter import ApplyAudioEventMessage, ApplyVisualEventMessage
from marsdog_ros2.personality_adapter import ApplyPersonalityStateMessage

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
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
        self.system = MarsdogNeedSystem()
        self.statePublisher = self.create_publisher(String, "/internal_need/state", 10)
        self.signalPublisher = self.create_publisher(String, "/internal_need/signal_event", 10)
        self.create_subscription(String, "/perception/visual_event", self.OnVisualEventMessage, _BestEffortQoS(5))
        self.create_subscription(String, "/perception/audio_event", self.OnAudioEventMessage, _ReliableQoS(10))
        self.create_subscription(String, "/behavior/result_event", self.OnBehaviorResultMessage, _ReliableQoS(10))
        self.create_subscription(String, "/personality/state", self.OnPersonalityStateMessage, _ReliableTransientLocalQoS(1))
        self.create_timer(1.0, self.PublishState)
        self.create_timer(600.0, self.UpdateDemandTick)

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

    def UpdateDemandTick(self) -> None:
        """每 10 分钟更新一次自然需求。"""
        self.system.UpdateNaturalDemandsByTime()
        self.PublishSignalEvents()

    def PublishState(self) -> None:
        """发布内部需求状态。"""
        message = String()
        message.data = json.dumps(self.system.GetInternalNeedStateValue(), ensure_ascii=False)
        self.statePublisher.publish(message)
        self.PublishSignalEvents()

    def PublishSignalEvents(self) -> None:
        """发布需求等级变化事件，未变化时不发布。"""
        for signalEvent in self.system.GetDemandSignalEventsValue():
            message = String()
            message.data = json.dumps(signalEvent, ensure_ascii=False)
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


def main(args=None) -> None:
    """启动内部需求计算节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = InternalNeedNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
