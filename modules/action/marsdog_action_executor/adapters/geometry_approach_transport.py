"""Public Vision ROI -> depth/TF service -> selected navigation backend."""
import copy
import math
import time

from .person_nav_approach_adapter import Ros2PersonApproachTransport


from ..geometry_contract import geometry_request

class GeometryApproachTransport(Ros2PersonApproachTransport):
    vision_task_type = 'locate_person_geometry'

    def __init__(self, node, *, local_adapter=None, **kwargs):
        super().__init__(node, **kwargs)
        self.local_adapter = local_adapter
        # Lazy type import: legacy routes do not require this optional capability.
        self._geometry = None
        self._geometry_type = None

    def locate(self, target_id, stand_off, deadline, cancel):
        payload, reason = super().locate(target_id, stand_off, deadline, cancel)
        if payload is None:
            return None, reason
        if cancel.is_set() or time.monotonic() >= deadline:
            return None, 'geometry_canceled_or_expired'
        try:
            header, roi = geometry_request(payload, target_id)
        except (ValueError, TypeError, AttributeError) as exc:
            return None, str(exc)
        if self._geometry is None:
            try:
                from person_3d_localization.srv import LocateFromBbox
                from rclpy.callback_groups import ReentrantCallbackGroup
                self._geometry_type = LocateFromBbox
                self._geometry = self._node.create_client(LocateFromBbox,
                    '/person_3d_localization/locate_from_bbox', callback_group=ReentrantCallbackGroup())
            except ImportError:
                return None, 'geometry_interface_unavailable'
        while not self._geometry.wait_for_service(timeout_sec=min(.1, max(0.0, deadline-time.monotonic()))):
            if cancel.is_set() or time.monotonic() >= deadline:
                return None, 'geometry_service_unavailable'
        if cancel.is_set() or time.monotonic() >= deadline:
            return None, 'geometry_canceled_or_expired'
        request = self._geometry_type.Request()
        request.image_header.frame_id = header['frame_id']
        request.image_header.stamp.sec = header['sec']
        request.image_header.stamp.nanosec = header['nanosec']
        for key, value in roi.items():
            setattr(request.bbox, key, value)
        request.stand_off_distance = float(stand_off)
        future = self._geometry.call_async(request)
        if not self._wait(future, deadline, cancel):
            self._geometry.remove_pending_request(future)
            future.cancel()
            return None, 'geometry_canceled_or_expired'
        if cancel.is_set() or time.monotonic() >= deadline:
            return None, 'geometry_canceled_or_expired'
        try:
            result = future.result()
            if not result.success or result.status != 0:
                return None, 'geometry_failed:%s:%s' % (result.status, result.message)
            point, pose = result.person_point, result.navigation_goal
            return {'ok': True, 'target_id': target_id, 'status': result.status,
                'navigation_required': result.navigation_required,
                'person_point': {'header': {'frame_id': point.header.frame_id},
                    'point': {k: getattr(point.point, k) for k in ('x', 'y', 'z')}},
                'navigation_goal': {'header': {'frame_id': pose.header.frame_id}, 'pose': {
                    'position': {k: getattr(pose.pose.position, k) for k in ('x', 'y', 'z')},
                    'orientation': {k: getattr(pose.pose.orientation, k) for k in ('x', 'y', 'z', 'w')}}}}, 'ok'
        except Exception as exc:
            return None, 'geometry_response_error:%s' % type(exc).__name__

    def navigate_approach(self, pose, deadline, cancel, *, ctx, unit_config):
        if ctx.params['approach']['mode'] == 'map_nav':
            return self.navigate(pose, deadline, cancel)
        if self.local_adapter is None:
            return False, False, 'approach_local_controller_unavailable'
        if cancel.is_set() or time.monotonic() >= deadline:
            return False, cancel.is_set(), 'canceled_or_expired_before_local_navigation'
        position, q = pose['pose']['position'], pose['pose']['orientation']
        yaw = math.atan2(2*(q['w']*q['z']+q['x']*q['y']), 1-2*(q['y']**2+q['z']**2))
        local_ctx = copy.copy(ctx)
        local_ctx.params = dict(ctx.params, local_motion={
            'unit_id': unit_config['unit_id'], 'mode': 'move',
            'target_id': ctx.target['target_id'], 'target_source': 'vision',
            'goal': {'frame_id': 'map', 'x': position['x'], 'y': position['y'], 'yaw': yaw},
            'parameters': {}})
        outcome = self.local_adapter.execute_task(unit_config, local_ctx,
            max(0.0, deadline-time.monotonic()), cancel_check=cancel.is_set)
        # Shared metadata keeps local stop confirmation in the outer Action result.
        return outcome.success, outcome.canceled, outcome.reason

    def cancel(self):
        super().cancel()
        if self.local_adapter is not None and self.local_adapter.active:
            self.local_adapter.request_cancel()
