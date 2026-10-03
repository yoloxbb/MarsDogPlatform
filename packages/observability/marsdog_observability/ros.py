"""Optional /rosout observer; native ROS call sites and filters remain untouched."""
def main():
    import json
    import os
    import signal
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.duration import Duration
    from rcl_interfaces.msg import Log
    from rclpy.signals import SignalHandlerOptions
    from .runtime import configure, shutdown
    session = configure("ros")
    mapping = json.loads(os.environ.get("MARSDOG_LOG_COMPONENT_MAP", "{}"))
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Node("marsdog_log_collector", enable_rosout=False)
    def receive(message):
        if session is not None:
            session.record("ros.message", {"source_component": mapping.get(message.name, "external"),
                "source_logger": message.name, "source_timestamp_ns": message.stamp.sec * 1000000000 + message.stamp.nanosec,
                "file": message.file, "function": message.function, "line": message.line},
                level=int(message.level), message=message.msg, logger=message.name)
    # Humble exposes this profile in rcl/logging_rosout.h, not rclpy.qos.
    qos = QoSProfile(depth=1000, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL, lifespan=Duration(seconds=10))
    node.create_subscription(Log, "/rosout", receive, qos)
    running = True
    def interrupt(signum, frame):
        nonlocal running
        running = False
    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        # Bounded wait lets Python signal handlers run even when /rosout is idle.
        while running and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        shutdown()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
