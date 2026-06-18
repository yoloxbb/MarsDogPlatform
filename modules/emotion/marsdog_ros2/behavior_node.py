"""ROS2 行为节点适配层。"""

from __future__ import annotations

import json

from marsdog_core import MarsdogBehaviorSystem
from marsdog_ros2.action_feedback_adapter import ApplyActionFeedbackMessage
from marsdog_ros2.perception_adapter import ApplyInteractionEventMessage, ApplyObservationMessage

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    Node = object
    String = None


class BehaviorNode(Node):
    """把 ROS2 输入输出转换为核心行为系统调用。"""

    def __init__(self) -> None:
        """初始化 ROS2 行为节点。"""
        if rclpy is None or String is None:
            raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

        super().__init__("marsdog_behavior_node")
        self.system = MarsdogBehaviorSystem()
        self.actionPublisher = self.create_publisher(String, "marsdog/action", 10)
        self.concreteActionPublisher = self.create_publisher(String, "marsdog/concrete_actions", 10)
        self.actionCommandPublisher = self.create_publisher(String, "marsdog/action_command", 10)
        self.create_subscription(String, "/perception/observation", self.OnObservationMessage, 10)
        self.create_subscription(String, "/perception/interaction_event", self.OnInteractionEventMessage, 10)
        self.create_subscription(String, "marsdog/action_feedback", self.OnActionFeedbackMessage, 10)
        self.create_timer(0.1, self.Tick)
        self.create_timer(600.0, self.UpdateDemandTick)

    def Tick(self) -> None:
        """周期性执行核心 Tick 并发布行为指令。"""
        self.system.Tick(applyDemandGrowth=False)
        actionMessage = String()
        actionMessage.data = self.system.GetCurrentAction()
        self.actionPublisher.publish(actionMessage)

        concreteActionMessage = String()
        concreteActionMessage.data = ",".join(self.system.GetConcreteActionQueue())
        self.concreteActionPublisher.publish(concreteActionMessage)

        actionCommandMessage = String()
        actionCommand = self.system.GetCurrentActionCommand()
        actionCommandMessage.data = json.dumps(actionCommand or {}, ensure_ascii=False)
        self.actionCommandPublisher.publish(actionCommandMessage)

    def UpdateDemandTick(self) -> None:
        """每 10 分钟更新一次随时间增长的需求。"""
        self.system.UpdateNaturalDemandsByTime()

    def OnObservationMessage(self, message) -> None:
        """处理感知理解层 observation 消息。"""
        ApplyObservationMessage(self.system, message)

    def OnInteractionEventMessage(self, message) -> None:
        """处理感知理解层 interaction_event 消息。"""
        ApplyInteractionEventMessage(self.system, message)

    def OnActionFeedbackMessage(self, message) -> None:
        """处理动作执行层反馈消息。"""
        ApplyActionFeedbackMessage(self.system, message)


def main(args=None) -> None:
    """启动 ROS2 行为节点。"""
    if rclpy is None:
        raise RuntimeError("ROS2 runtime is not available. Please run this node inside a ROS2 environment.")

    rclpy.init(args=args)
    node = BehaviorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
