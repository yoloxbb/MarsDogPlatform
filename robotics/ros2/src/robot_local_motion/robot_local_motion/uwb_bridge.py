"""Optional bridge from the existing UWB adapter's stamped point to a typed target."""
import math
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped
from robot_local_motion.msg import TargetObservation


class UwbObservationBridge(Node):
    def __init__(self):
        super().__init__('uwb_observation_bridge')
        topic = self.declare_parameter('input_topic', '/uwb/target_point').value
        output = self.declare_parameter('output_topic', '/robot_local_motion/target').value
        self.identity = self.declare_parameter('target_id', 'owner').value
        self.source = self.declare_parameter('source', 'uwb').value
        self.sequence = time.time_ns()
        self.last_stamp = 0
        self.pub = self.create_publisher(TargetObservation, output, 10)
        self.sub = self.create_subscription(PointStamped, topic, self.observe, 10)

    def observe(self, point):
        stamp = point.header.stamp.sec * 10**9 + point.header.stamp.nanosec
        if stamp <= self.last_stamp or not point.header.frame_id:
            return
        self.last_stamp = stamp
        self.sequence += 1
        observation = TargetObservation()
        observation.header = point.header
        observation.position = point.point
        observation.target_id, observation.source = self.identity, self.source
        observation.sequence = self.sequence
        observation.confidence = 1.0  # Transport validity, not a fabricated UWB accuracy estimate.
        observation.valid = all(math.isfinite(v) for v in (point.point.x, point.point.y, point.point.z))
        self.pub.publish(observation)


def main():
    rclpy.init()
    node = UwbObservationBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
