"""ROS2 情绪计算节点。"""

from __future__ import annotations

import json

from marsdog_core.emotion_system import MarsdogEmotionSystem
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


class EmotionEngineNode(Node):
    """发布情绪状态和表达阈值触发信号。"""

    def __init__(self) -> None:
        """初始化情绪 ROS2 节点。"""
        if rclpy is None or String is None:
            raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

        super().__init__("emotion_engine_node")
        self.system = MarsdogEmotionSystem()
        self.statePublisher = self.create_publisher(String, "/emotion/state", 10)
        self.signalPublisher = self.create_publisher(String, "/emotion/signal_event", 10)
        self.create_subscription(String, "/perception/visual_event", self.OnVisualEventMessage, _BestEffortQoS(5))
        self.create_subscription(String, "/perception/audio_event", self.OnAudioEventMessage, _ReliableQoS(10))
        self.create_subscription(String, "/behavior/result_event", self.OnBehaviorResultMessage, _ReliableQoS(10))
        self.create_subscription(String, "/personality/state", self.OnPersonalityStateMessage, _ReliableTransientLocalQoS(1))
        self.create_timer(1.0, self.Tick)

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

    def Tick(self) -> None:
        """执行 1 秒情绪自然平复并发布状态。"""
        self.system.ApplyEmotionDecay(1.0)
        self.PublishSignalEvents()
        self.PublishState()

    def PublishState(self) -> None:
        """发布情绪状态。"""
        message = String()
        message.data = json.dumps(self.system.GetEmotionStateValue(), ensure_ascii=False)
        self.statePublisher.publish(message)

    def PublishSignalEvents(self) -> None:
        """发布情绪区间变化事件，未变化时不发布。"""
        for signalEvent in self.system.GetEmotionSignalEventsValue():
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
    """启动情绪计算节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = EmotionEngineNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
