"""Relay a standard odometry pose into TF, with one explicit TF owner."""

import math
from copy import deepcopy

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


def split_odometry_transforms(message, odom_frame, input_base_frame,
                             footprint_frame, body_frame, body_height=None):
    """Separate planar navigation from the supplied body attitude and height.

    A yaw-only vendor pose cannot recover physical roll/pitch. The measured
    height is independent of the vendor's reserved zero z field.
    """
    if (input_base_frame != body_frame or
            len({odom_frame, footprint_frame, body_frame}) != 3):
        raise ValueError('分层 TF 的 odom、base_footprint、body_frame 必须不同，输入 child 必须为机身')
    source = odometry_transform(message, odom_frame, input_base_frame)
    q = source.transform.rotation
    norm = math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w)
    x, y, z, w = (value/norm for value in (q.x, q.y, q.z, q.w))
    yaw = math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))
    sine, cosine = math.sin(yaw/2), math.cos(yaw/2)
    footprint = deepcopy(source)
    footprint.child_frame_id = footprint_frame
    footprint.transform.translation.z = 0.0
    footprint.transform.rotation.x = 0.0
    footprint.transform.rotation.y = 0.0
    footprint.transform.rotation.z = sine
    footprint.transform.rotation.w = cosine
    transforms = [footprint]
    if body_height is None:
        return transforms
    if (isinstance(body_height, bool) or not math.isfinite(body_height) or body_height <= 0):
        raise ValueError('机身离地高度必须为实测正数')
    body = TransformStamped()
    body.header.stamp = deepcopy(message.header.stamp)
    body.header.frame_id = footprint_frame
    body.child_frame_id = body_frame
    body.transform.translation.z = body_height
    # R_body = Rz(yaw) * R_residual; do not apply yaw twice.
    body.transform.rotation.x = cosine*x + sine*y
    body.transform.rotation.y = cosine*y - sine*x
    body.transform.rotation.z = cosine*z - sine*w
    body.transform.rotation.w = cosine*w + sine*z
    transforms.append(body)
    return transforms


class OdometryTfRelay(Node):
    """Publish TF and optional reliable odometry; never request motion control."""

    def __init__(self):
        super().__init__('odometry_tf_relay')
        self.odom_frame = self.declare_parameter('odom_frame', 'odom').value
        self.base_frame = self.declare_parameter('base_frame', 'base_link').value
        self.input_base_frame = self.declare_parameter('input_base_frame', '').value or self.base_frame
        self.body_frame = self.declare_parameter('body_frame', 'base_link').value
        self.split_base_frames = self.declare_parameter('split_base_frames', False).value
        height = self.declare_parameter('body_height', 0.0).value
        if not math.isfinite(height) or height < 0:
            raise ValueError('body_height 必须是有限非负值；0 表示尚未配置')
        self.body_height = height if height > 0 else None
        if self.split_base_frames and self.body_height is None:
            self.get_logger().warning('机身离地高度待测；仅发布 odom -> base_footprint，不发布未知机身高度')
        topic = self.declare_parameter('odom_topic', '/odom').value
        output = self.declare_parameter('output_odom_topic', '').value
        if output and self.resolve_topic_name(output) == self.resolve_topic_name(topic):
            raise ValueError('里程计转发的输入和输出话题不能相同')
        self.odom_publisher = self.create_publisher(Odometry, output, 10) if output else None
        self.broadcaster = TransformBroadcaster(self)
        self.subscription = self.create_subscription(
            Odometry, topic, self.on_odometry, qos_profile_sensor_data)

    def on_odometry(self, message):
        """Ignore invalid samples instead of inventing poses or timestamps."""
        try:
            if self.split_base_frames:
                transform = split_odometry_transforms(
                    message, self.odom_frame, self.input_base_frame,
                    self.base_frame, self.body_frame, self.body_height)
            else:
                transform = odometry_transform(message, self.odom_frame, self.base_frame)
        except ValueError as error:
            self.get_logger().warning(str(error), throttle_duration_sec=5)
            return
        self.broadcaster.sendTransform(transform)
        if self.odom_publisher is not None:
            # Preserve vendor pose, twist, covariance, frames and timestamp exactly.
            self.odom_publisher.publish(message)


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
