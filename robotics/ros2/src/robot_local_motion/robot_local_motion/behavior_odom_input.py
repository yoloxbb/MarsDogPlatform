"""Convert Odometry's child reference to the legacy behavior's base frame.

The existing behavior expects child_frame_id == base_frame. This input adapter
uses the measured TF, including lever-arm velocity/covariance, rather than
changing the behavior or relabelling base_link as base_footprint.
"""
import copy
import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener
from .target_geometry import rotate


def skew(v):
    x, y, z = v
    return np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])


def convert_odom(msg, child_to_base, base):
    result = copy.deepcopy(msg)
    if msg.child_frame_id == base:
        return result
    t, q = child_to_base.translation, child_to_base.rotation
    offset = np.array([t.x, t.y, t.z])
    qb = (q.x, q.y, q.z, q.w)
    inverse = (-q.x, -q.y, -q.z, q.w)
    rotation = np.column_stack([rotate(inverse, axis) for axis in np.eye(3)])
    pose = msg.pose.pose
    qp = pose.orientation
    qw = (qp.x, qp.y, qp.z, qp.w)
    lever = np.array(rotate(qw, offset))
    xyz = np.array([pose.position.x, pose.position.y, pose.position.z])+lever
    result.pose.pose.position.x, result.pose.pose.position.y, result.pose.pose.position.z = map(float, xyz)
    ax, ay, az, aw = qw
    bx, by, bz, bw = qb
    qr = result.pose.pose.orientation
    qr.x, qr.y, qr.z, qr.w = (aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                              aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz)
    v, w = msg.twist.twist.linear, msg.twist.twist.angular
    angular = np.array([w.x, w.y, w.z])
    linear = rotation@(np.array([v.x, v.y, v.z])+np.cross(angular, offset))
    angular = rotation@angular
    result.twist.twist.linear.x, result.twist.twist.linear.y, result.twist.twist.linear.z = map(float, linear)
    result.twist.twist.angular.x, result.twist.twist.angular.y, result.twist.twist.angular.z = map(float, angular)
    for field, jacobian in [('pose', np.block([[np.eye(3), -skew(lever)], [np.zeros((3, 3)), np.eye(3)]])),
                            ('twist', np.block([[rotation, -rotation@skew(offset)], [np.zeros((3, 3)), rotation]]))]:
        cov = np.array(getattr(msg, field).covariance).reshape(6, 6)
        getattr(result, field).covariance = list((jacobian@cov@jacobian.T).flat)
    result.child_frame_id = base
    return result


class BehaviorOdomInput(Node):
    def __init__(self, **kwargs):
        super().__init__('behavior_odom_input', **kwargs)
        p = lambda key, default: self.declare_parameter(key, default).value
        self.base = p('base_frame', 'base_footprint')
        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        self.pending = None
        self.output = self.create_publisher(Odometry, p('output_topic', '/target_follow/behavior_odom'), qos_profile_sensor_data)
        self.create_subscription(Odometry, p('odom_topic', '/odom'), self.receive, qos_profile_sensor_data)
        self.create_timer(.02, self.tick)

    def receive(self, msg):
        self.pending = msg

    def tick(self):
        if self.pending is None:
            return
        msg = self.pending
        try:
            if msg.child_frame_id == self.base:
                result = msg
            else:
                tf = self.tf.lookup_transform(msg.child_frame_id, self.base, Time.from_msg(msg.header.stamp))
                result = convert_odom(msg, tf.transform, self.base)
            self.output.publish(result)
            self.pending = None
        except TransformException:
            pass


def main():
    rclpy.init()
    node = BehaviorOdomInput()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
