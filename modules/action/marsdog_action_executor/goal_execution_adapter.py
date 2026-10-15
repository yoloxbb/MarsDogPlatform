"""ROS shell composition only; no orchestration or copied mutable state."""
from .motion_ownership import controllers_for_node, unresolved_controllers
from .goal_execution_ports import ExecutionPorts, ExecutionRuntime


class _NodeState:
    def __init__(self, node):
        self._node = node

    @property
    def current_priority(self):
        return getattr(self._node, '_current_priority', 0)

    @current_priority.setter
    def current_priority(self, value):
        self._node._current_priority = value

    @property
    def reserved_goal_id(self):
        return getattr(self._node, '_reserved_goal_id', None)

    @reserved_goal_id.setter
    def reserved_goal_id(self, value):
        self._node._reserved_goal_id = value

    @property
    def long_goal_id(self):
        return getattr(self._node, '_long_goal_id', None)

    @long_goal_id.setter
    def long_goal_id(self, value):
        self._node._long_goal_id = value


def for_node(node) -> ExecutionRuntime:
    def stop_motion():
        node._interrupt.request_cancel()
        controllers = dict(controllers_for_node(node), chassis=getattr(node, '_chassis_backend', None))
        for controller in controllers.values():
            stop = getattr(controller, 'emergency_stop', None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    # Try every stop outlet and preserve the original failure.
                    pass
    return ExecutionRuntime(_NodeState(node), ExecutionPorts(
        approach_adapters=getattr(node, '_approach_adapters', {}),
        approach_navigation_adapter=getattr(node, '_approach_navigation_adapter', None),
        behavior_execution_lock=getattr(node, '_behavior_execution_lock', None),
        behavior_resolver=getattr(node, '_behavior_resolver', None),
        behavior_sounds=getattr(node, '_behavior_sounds', None),
        chassis_backend=getattr(node, '_chassis_backend', None),
        config=getattr(node, '_config', None),
        controller_routes=getattr(node, '_controller_routes', None),
        debug=getattr(node, '_debug', None),
        execute_behavior=lambda *a, **kw: node._execute_behavior(*a, **kw),
        execute_emergency_stop=lambda *a, **kw: node._execute_emergency_stop(*a, **kw),
        execute_long_behavior=lambda *a, **kw: node._execute_long_behavior(*a, **kw),
        goal_parser=getattr(node, '_goal_parser', None),
        goal_reservation_lock=getattr(node, '_goal_reservation_lock', None),
        interrupt=getattr(node, '_interrupt', None),
        lease_expired=lambda *a, **kw: node._lease_expired(*a, **kw),
        lease_lock=getattr(node, '_lease_lock', None),
        lease_seen=getattr(node, '_lease_seen', None),
        local_motion_adapter=getattr(node, '_local_motion_adapter', None),
        mobility_adapter=getattr(node, '_mobility_adapter', None),
        person_nav_approach_adapter=getattr(node, '_person_nav_approach_adapter', None),
        posture=getattr(node, '_posture', None),
        publish_feedback=lambda *a, **kw: node._publish_feedback(*a, **kw),
        result_evaluator=getattr(node, '_result_evaluator', None),
        stage_executor=getattr(node, '_stage_executor', None),
        stationary_expression_adapter=getattr(node, '_stationary_expression_adapter', None),
        target_approach_adapter=getattr(node, '_target_approach_adapter', None),
        uwb_follow_adapter=getattr(node, '_uwb_follow_adapter', None),
        uwb_roam_adapter=getattr(node, '_uwb_roam_adapter', None),
        visual_target_approach_adapter=getattr(node, '_visual_target_approach_adapter', None),
        wake_orientation_adapter=getattr(node, '_wake_orientation_adapter', None),
        waypoint_nav_client=getattr(node, '_waypoint_nav_client', None),
        get_logger=lambda *a, **kw: node.get_logger(*a, **kw),
        preempt_lock_wait_sec=lambda: float(node.get_parameter('navigation_preempt_lock_wait_sec').value),
        motion_ownership=getattr(node, '_motion_ownership', None),
        stop_motion=stop_motion,
        motion_lease_for=lambda handle: getattr(node, '_goal_motion_leases', {}).get(id(handle)),
        forget_motion_lease=lambda handle: getattr(node, '_goal_motion_leases', {}).pop(id(handle), None),
        unresolved_motion=lambda: unresolved_controllers(controllers_for_node(node)),
    ))
