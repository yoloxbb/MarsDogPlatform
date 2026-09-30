"""ExecuteBehavior message construction with injected generated type factories.

The ROS identity is still selected by ros_node; no silent constructor field drops.
"""
from __future__ import annotations
import json
from .models import ExecutionResult, ExecutionFeedback


def make_result(goal_id: str, behavior_id: str, behavior_name: str, resolved_name: str='', status: str='SUCCESS', result: str='completed', reason: str='', reward: float=1.0, metadata: dict | None=None, *, action_type):
    """Build an ExecuteBehavior.Result with explicit field assignment.

    Uses attribute assignment rather than constructor kwargs to avoid
    silent field drops that can occur with ROS2 action message types.
    """
    if action_type is None:
        return ExecutionResult(
            goal_id=goal_id,
            behavior_id=behavior_id,
            behavior_name=str(resolved_name or behavior_name),
            status=str(status),
            result=str(result),
            reason=str(reason),
            reward=float(reward),
            emotion_delta_json="{}",
            need_delta_json="{}",
            metadata_json=json.dumps(metadata) if metadata else "{}",
        )
    r = action_type.Result()
    r.goal_id = goal_id
    r.behavior_id = behavior_id
    r.behavior_name = str(resolved_name or behavior_name)
    r.status = str(status)
    r.result = str(result)
    r.reason = str(reason)
    r.reward = float(reward)
    r.emotion_delta_json = "{}"
    r.need_delta_json = "{}"
    r.metadata_json = json.dumps(metadata) if metadata else "{}"
    return r

def publish_feedback(self, goal_handle, gid: str, behavior_id: str, behavior_name: str, progress: float, stage: str, action: str, safe: bool, message: str, *, action_type):
    """Publish feedback via Action + debug topic."""
    if action_type:
        fb = action_type.Feedback()
        fb.goal_id = gid
        fb.behavior_id = behavior_id
        fb.behavior_name = behavior_name
        fb.status = "RUNNING"
        fb.progress = progress
        fb.safe_to_interrupt = safe
        fb.current_action = action
        fb.message = message
        goal_handle.publish_feedback(fb)

    debug_fb = ExecutionFeedback(
        goal_id=gid,
        behavior_id=behavior_id,
        behavior_name=behavior_name,
        status="RUNNING",
        progress=progress,
        current_stage=stage,
        current_action=action,
        safe_to_interrupt=safe,
        message=message,
    )
    self._debug.publish_feedback(debug_fb)
