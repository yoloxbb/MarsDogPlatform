"""Finish Nav2 lifecycle while ROS contexts are still valid."""
import json
import os
from pathlib import Path
import sys
import time

def main():
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    import rclpy
    from nav2_msgs.srv import ManageLifecycleNodes
    rclpy.init()
    node = rclpy.create_node("marsdog_local_nav2_shutdown")
    report = {"status": "FAIL", "operation": "ManageLifecycleNodes.SHUTDOWN"}
    try:
        client = node.create_client(ManageLifecycleNodes, "/lifecycle_manager/manage_nodes")
        if not client.wait_for_service(timeout_sec=2.0):
            raise RuntimeError("Nav2 lifecycle manager unavailable during shutdown")
        request = ManageLifecycleNodes.Request(command=ManageLifecycleNodes.Request.SHUTDOWN)
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=6.0)
        if not future.done() or not future.result().success:
            raise RuntimeError("Nav2 lifecycle shutdown was not confirmed")
        report["status"] = "PASS"
    except BaseException as exc:
        report["error"] = str(exc)
    finally:
        Path(sys.argv[1]).write_text(json.dumps(report, indent=2)+"\n")
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
    if report["status"] != "PASS":
        raise RuntimeError(report["error"])

if __name__ == "__main__":
    main()
