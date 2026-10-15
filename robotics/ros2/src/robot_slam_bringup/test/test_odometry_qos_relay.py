"""ROS transport regression using synthetic input in an isolated domain."""

import os
import time
import unittest

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy

from robot_slam_bringup.odometry_tf_relay import OdometryTfRelay


class OdometryQosRelayTest(unittest.TestCase):
    def test_reliable_receiver_gets_unchanged_best_effort_input(self):
        # Never let a test bind to the deployment domain or robot topics.
        if os.environ.get('ROS_DOMAIN_ID') != '86' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
            self.fail('Run with ROS_DOMAIN_ID=86 ROS_LOCALHOST_ONLY=1')
        rclpy.init(args=['--ros-args', '-p', 'odom_topic:=/test/vendor_odom',
                        '-p', 'output_odom_topic:=/test/nav2_odom'])
        relay = OdometryTfRelay()
        probe = rclpy.create_node('odometry_qos_regression', use_global_arguments=False)
        received = []
        source = probe.create_publisher(
            Odometry, '/test/vendor_odom', QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT))
        probe.create_subscription(Odometry, '/test/nav2_odom', received.append, 10)
        message = Odometry()
        message.header.frame_id = 'odom'
        message.child_frame_id = 'base_link'
        message.header.stamp.sec = 123
        message.header.stamp.nanosec = 456
        message.pose.pose.orientation.w = 1.0
        message.pose.pose.position.x = 1.25
        message.pose.covariance[0] = -1.0
        message.twist.twist.linear.x = 0.12
        message.twist.covariance[0] = -1.0
        try:
            deadline = time.monotonic() + 5.0
            while not received and time.monotonic() < deadline:
                source.publish(message)
                rclpy.spin_once(relay, timeout_sec=0.02)
                rclpy.spin_once(probe, timeout_sec=0.02)
            self.assertTrue(received, 'Reliable receiver did not receive forwarded odometry')
            self.assertEqual(received[-1], message)
            self.assertTrue(all(
                info.qos_profile.reliability == ReliabilityPolicy.RELIABLE
                for info in probe.get_publishers_info_by_topic('/test/nav2_odom')))
            received.clear()
            message.pose.pose.orientation.w = 0.0
            deadline = time.monotonic() + 0.3
            # Drain a valid sample still in the transport queue before sending bad input.
            while time.monotonic() < deadline:
                rclpy.spin_once(relay, timeout_sec=0.01)
                rclpy.spin_once(probe, timeout_sec=0.01)
            received.clear()
            source.publish(message)
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                rclpy.spin_once(relay, timeout_sec=0.01)
                rclpy.spin_once(probe, timeout_sec=0.01)
            self.assertEqual(received, [], 'Invalid odometry must not be forwarded')
        finally:
            probe.destroy_node()
            relay.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
