"""Relay a standard odometry pose into TF, with one explicit TF owner."""

import math

from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from tf2_ros import TransformBroadcaster


def odometry_transform(message, odom_frame, base_frame):
    """Preserve pose and timestamp; reject incompatible or invalid samples."""
    if (message.header.frame_id != odom_frame or
            message.child_frame_id != base_frame):
        raise ValueError('Odometry 的 frame_id/child_frame_id 与所选机器人不一致')
    if message.header.stamp.sec == 0 and message.header.stamp.nanosec == 0:
        raise ValueError('Odometry 时间戳为零')
    pose = message.pose.pose
    values = (pose.position.x, pose.position.y, pose.position.z,
              pose.orientation.x, pose.orientation.y,
              pose.orientation.z, pose.orientation.w)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Odometry 位姿包含非有限值')
    norm = math.sqrt(sum(value * value for value in values[3:]))
    if abs(norm - 1.0) > 0.01:
        raise ValueError('Odometry 四元数未归一化')
    transform = TransformStamped()
    transform.header = message.header
    transform.child_frame_id = message.child_frame_id
    transform.transform.translation.x = pose.position.x
    transform.transform.translation.y = pose.position.y
    transform.transform.translation.z = pose.position.z
    transform.transform.rotation = pose.orientation
    return transform


class OdometryTfRelay(Node):
    """Publish only odom-to-base TF; never publish velocities or request control."""

    def __init__(self):
        super().__init__('odometry_tf_relay')
        self.odom_frame = self.declare_parameter('odom_frame', 'odom').value
        self.base_frame = self.declare_parameter('base_frame', 'base_link').value
        topic = self.declare_parameter('odom_topic', '/odom').value
        self.broadcaster = TransformBroadcaster(self)
        self.subscription = self.create_subscription(
            Odometry, topic, self.on_odometry, qos_profile_sensor_data)

    def on_odometry(self, message):
        """Ignore invalid samples instead of inventing poses or timestamps."""
        try:
            transform = odometry_transform(message, self.odom_frame, self.base_frame)
        except ValueError as error:
            self.get_logger().warning(str(error), throttle_duration_sec=5)
            return
        self.broadcaster.sendTransform(transform)


def main(args=None):
    rclpy.init(args=args)
    node = OdometryTfRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
