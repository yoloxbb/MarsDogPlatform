"""Ideal 2-D kinematics and synthetic inputs for real Nav2, never a Lite3 driver."""
import math
import os
import time

def main():
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    assert 180 <= int(os.environ["ROS_DOMAIN_ID"]) <= 219
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from geometry_msgs.msg import Twist, TransformStamped, PoseStamped
    from nav_msgs.msg import OccupancyGrid, Odometry
    from sensor_msgs.msg import Image
    from std_srvs.srv import SetBool
    from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster

    class Inputs(Node):
        def __init__(self):
            super().__init__("marsdog_nav2_simulated_inputs")
            self.x, self.y, self.yaw = 0.5, 1.0, 0.0
            self.vx = self.vy = self.wz = 0.0
            self.last_command = self.previous = time.monotonic()
            self.frozen = False
            self.tf = TransformBroadcaster(self)
            self.static = StaticTransformBroadcaster(self)
            transform = TransformStamped()
            transform.header.stamp = self.get_clock().now().to_msg()
            transform.header.frame_id, transform.child_frame_id = "map", "odom"
            transform.transform.rotation.w = 1.0
            self.static.sendTransform(transform)
            self.odom = self.create_publisher(Odometry, "/odom", 10)
            self.pose = self.create_publisher(PoseStamped, "/development/nav2/pose", 10)
            self.images = self.create_publisher(Image, "/camera/mock_image_raw", 10)
            self.maps = self.create_publisher(OccupancyGrid, "/map",
                QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self.create_subscription(Twist, "/development/nav2/cmd_vel", self.velocity, 10)
            self.create_service(SetBool, "/development/nav2/freeze", self.freeze)
            self.create_timer(0.02, self.tick)
            self.create_timer(0.1, self.image)
            self.create_timer(1.0, self.grid)
            self.grid()
        def velocity(self, message):
            self.vx, self.vy, self.wz = message.linear.x, message.linear.y, message.angular.z
            self.last_command = time.monotonic()
        def freeze(self, request, response):
            self.frozen = request.data
            response.success = True
            response.message = "SIMULATED kinematics freeze=" + str(self.frozen)
            return response
        def tick(self):
            now = time.monotonic()
            dt, self.previous = min(now - self.previous, 0.1), now
            active = not self.frozen and now - self.last_command < 0.3
            vx, vy, wz = (self.vx, self.vy, self.wz) if active else (0.0, 0.0, 0.0)
            self.x += (vx * math.cos(self.yaw) - vy * math.sin(self.yaw)) * dt
            self.y += (vx * math.sin(self.yaw) + vy * math.cos(self.yaw)) * dt
            self.yaw += wz * dt
            msg = Odometry()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id, msg.child_frame_id = "odom", "base_link"
            msg.pose.pose.position.x, msg.pose.pose.position.y = self.x, self.y
            msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(self.yaw/2), math.cos(self.yaw/2)
            msg.twist.twist.linear.x, msg.twist.twist.linear.y = vx, vy
            msg.twist.twist.angular.z = wz
            self.odom.publish(msg)
            pose = PoseStamped(pose=msg.pose.pose)
            pose.header.stamp = msg.header.stamp
            pose.header.frame_id = "map"
            self.pose.publish(pose)
            tf = TransformStamped()
            tf.header, tf.child_frame_id = msg.header, "base_link"
            tf.transform.translation.x, tf.transform.translation.y = self.x, self.y
            tf.transform.rotation = msg.pose.pose.orientation
            self.tf.sendTransform(tf)
        def image(self):
            msg = Image()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "simulated_camera"
            msg.height, msg.width, msg.step, msg.encoding = 48, 64, 192, "bgr8"
            msg.data = bytes(48 * 192)
            self.images.publish(msg)
        def grid(self):
            msg = OccupancyGrid()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "map"
            msg.info.width = msg.info.height = 80
            msg.info.resolution = 0.1
            msg.info.origin.orientation.w = 1.0
            msg.data = [100 if x in (0,79) or y in (0,79) or (x == 30 and y < 25)
                        else 0 for y in range(80) for x in range(80)]
            self.maps.publish(msg)
    rclpy.init()
    node = Inputs()
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
