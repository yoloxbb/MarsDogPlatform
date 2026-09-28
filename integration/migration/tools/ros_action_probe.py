"""Hardware-free client/server using the ACTUAL generated historical ROS action type."""
from __future__ import annotations

import argparse
import json
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["server", "client"])
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    import rclpy
    from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from action_msgs.msg import GoalStatus
    from marsdog_action_executor.action import ExecuteBehavior

    rclpy.init()
    node = rclpy.create_node("migration_probe_" + args.role)
    if args.role == "server":
        def accept(request):
            print(json.dumps({"phase": "goal_received", "goal_id": request.goal_id}), flush=True)
            return GoalResponse.ACCEPT

        def execute(goal_handle):
            print(json.dumps({"phase": "execute", "goal_id": goal_handle.request.goal_id}), flush=True)
            feedback = ExecuteBehavior.Feedback()
            feedback.goal_id = goal_handle.request.goal_id
            feedback.behavior_id = goal_handle.request.behavior_id
            feedback.behavior_name = goal_handle.request.behavior_name
            feedback.status = "RUNNING"
            feedback.progress = 0.25
            feedback.safe_to_interrupt = True
            feedback.current_action = "test_only_no_motion"
            goal_handle.publish_feedback(feedback)
            cancel_mode = goal_handle.request.behavior_name == "test_cancel"
            if cancel_mode:
                deadline = time.monotonic() + 10
                while not goal_handle.is_cancel_requested and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not goal_handle.is_cancel_requested:
                    goal_handle.abort()
                else:
                    # Deliberately acknowledge cancel before terminal result.
                    time.sleep(0.35)
                    goal_handle.canceled()
            else:
                time.sleep(0.15)
                goal_handle.succeed()
            result = ExecuteBehavior.Result()
            result.goal_id = goal_handle.request.goal_id
            result.behavior_id = goal_handle.request.behavior_id
            result.behavior_name = goal_handle.request.behavior_name
            result.status = "CANCELED" if cancel_mode else "SUCCESS"
            result.result = "canceled" if cancel_mode else "completed"
            result.reason = "P1 transport fixture, no production executor or hardware"
            result.metadata_json = goal_handle.request.params_json
            result.emotion_delta_json = "{}"
            result.need_delta_json = "{}"
            print(json.dumps({"phase": "result", "status": result.status}), flush=True)
            return result

        server = ActionServer(
            node, ExecuteBehavior, args.endpoint, execute_callback=execute,
            goal_callback=accept,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup(),
        )
        executor = MultiThreadedExecutor(num_threads=3)
        executor.add_node(node)
        print(json.dumps({"phase": "ready", "endpoint": args.endpoint}), flush=True)
        try:
            executor.spin()
        except KeyboardInterrupt:
            pass
        finally:
            server.destroy()
            executor.shutdown()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        return

    feedback = []
    client = ActionClient(node, ExecuteBehavior, args.endpoint)

    def await_future(future, timeout=10):
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done():
            raise RuntimeError("ROS future timed out")
        return future.result()

    checks = {}
    try:
        if not client.wait_for_server(timeout_sec=15):
            raise RuntimeError("Test-only action server discovery timed out")
        goal = ExecuteBehavior.Goal()
        goal.goal_id = "p1-success"
        goal.behavior_id = "p1-behavior"
        goal.behavior_name = "test_success"
        goal.params_json = json.dumps({"energyValue": 88})
        goal.timeout_sec = 5.0
        handle = await_future(client.send_goal_async(goal, feedback_callback=feedback.append))
        assert handle.accepted
        result = await_future(handle.get_result_async())
        assert result.status == GoalStatus.STATUS_SUCCEEDED
        assert result.result.goal_id == goal.goal_id
        assert json.loads(result.result.metadata_json) == {"energyValue": 88}
        assert any(f.feedback.safe_to_interrupt and f.feedback.progress == 0.25 for f in feedback)
        checks["goal_feedback_metadata_result"] = "PASS"
        goal.goal_id = "p1-cancel"
        goal.behavior_name = "test_cancel"
        handle = await_future(client.send_goal_async(goal))
        assert handle.accepted
        result_future = handle.get_result_async()
        cancel = await_future(handle.cancel_goal_async())
        assert cancel.goals_canceling
        ack_at = time.monotonic()
        assert not result_future.done(), "Cancel ACK must not be mistaken for terminal result"
        result = await_future(result_future)
        delay = time.monotonic() - ack_at
        assert delay >= 0.15, delay
        assert result.status == GoalStatus.STATUS_CANCELED
        assert result.result.status == "CANCELED"
        checks["cancel_ack_separate_from_terminal_result"] = "PASS"
        checks["terminal_delay_after_cancel_ack_sec"] = round(delay, 3)
        print(json.dumps({
            "status": "PASS",
            "scope": "Real generated ROS IDL and two-process DDS; fake server; NO robot behavior validation",
            "type": "marsdog_action_executor/action/ExecuteBehavior",
            "endpoint": args.endpoint, "checks": checks,
        }))
    finally:
        client.destroy()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
