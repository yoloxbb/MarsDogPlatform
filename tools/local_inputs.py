"""Explicit synthetic image/map and Nav2 server for local integration, no hardware."""
import json
import os
import time

def main():
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.action import ActionServer, GoalResponse, CancelResponse
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import OccupancyGrid
    from sensor_msgs.msg import Image
    from std_msgs.msg import String

    class Inputs(Node):
        def __init__(self):
            super().__init__("marsdog_local_simulated_inputs")
            self.image_pub = self.create_publisher(Image, "/camera/mock_image_raw", 10)
            self.map_pub = self.create_publisher(OccupancyGrid, "/map",
                QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self.events = self.create_publisher(String, "/development/nav2_events", 10)
            self.create_timer(0.1, self.image)
            self.create_timer(1.0, self.grid)
            self.server = ActionServer(self, NavigateToPose, "/navigate_to_pose", self.execute,
                goal_callback=lambda _: GoalResponse.ACCEPT,
                cancel_callback=lambda _: CancelResponse.ACCEPT,
                callback_group=ReentrantCallbackGroup())
            self.get_logger().warning("SIMULATED camera/map/Nav2: no planning, sensors or motion")
        def image(self):
            image = Image()
            image.header.stamp = self.get_clock().now().to_msg()
            image.header.frame_id = "simulated_camera"
            image.height, image.width, image.step, image.encoding = 48, 64, 192, "bgr8"
            image.data = bytes(48 * 192)
            self.image_pub.publish(image)
        def grid(self):
            grid = OccupancyGrid()
            grid.header.stamp = self.get_clock().now().to_msg()
            grid.header.frame_id = "map"
            grid.info.width = grid.info.height = 80
            grid.info.resolution = 0.1
            grid.info.origin.orientation.w = 1.0
            grid.data = [0] * 6400
            self.map_pub.publish(grid)
        def execute(self, handle):
            goal_id = bytes(handle.goal_id.uuid).hex()
            self.events.publish(String(data=json.dumps({
                "simulated": True, "state": "ACCEPTED", "goal_id": goal_id})))
            deadline = time.monotonic() + 0.6
            while rclpy.ok() and time.monotonic() < deadline:
                if handle.is_cancel_requested:
                    handle.canceled()
                    state = "CANCELED"
                    break
                time.sleep(0.02)
            else:
                if rclpy.ok():
                    handle.succeed()
                    state = "SUCCEEDED"
                else:
                    handle.abort()
                    state = "ABORTED"
            self.events.publish(String(data=json.dumps({
                "simulated": True, "state": state, "goal_id": goal_id})))
            return NavigateToPose.Result()

    rclpy.init()
    node = Inputs()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown(timeout_sec=2)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == "__main__":
    main()
