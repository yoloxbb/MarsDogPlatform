"""Adapt live observations or one fixed odom point to the original follow node."""
from collections import deque
import json
import math
import struct

import rclpy
from geometry_msgs.msg import PointStamped
from nav_msgs.msg import Odometry
from rcl_interfaces.srv import SetParametersAtomically
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
from .target_geometry import bbox_point, transform_point


class FollowInput(Node):
    def __init__(self, **kwargs):
        super().__init__('target_follow_input', **kwargs)
        p = lambda key, default: self.declare_parameter(key, default).value
        self.mode = p('input_mode', 'stream')
        self.kind = p('input_kind', 'point')
        if self.mode not in ('stream', 'fixed') or self.kind not in ('point', 'uwb', 'vision'):
            raise ValueError('input_mode: stream/fixed; input_kind: point/uwb/vision')
        self.base = p('base_frame', 'base_footprint')
        self.odom_frame = p('odom_frame', 'odom')
        self.tag = p('target_id', '')
        self.source = p('target_source', 'uwb_multitag')
        self.label = p('vision_label', '')
        self.vision_id = p('vision_target_id', '')
        self.sync_delta = p('depth_sync_tolerance_sec', .1)
        self.radius = p('depth_sample_radius_px', 2)
        self.armed = p('autostart', False)
        self.manage = p('manage_tracking', True)
        self.applied = None
        self.reset_requested = False
        self.future = None
        self.goal = self.pending = self.odom = self.info = None
        self.vision_message = None
        self.published_ns = 0
        self.depths = deque(maxlen=30)
        self.message = ''
        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        self.output = self.create_publisher(PointStamped, p('selected_target_topic', '/target_follow/selected_target'), 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.fixed_output = self.create_publisher(PointStamped, p('fixed_goal_topic', '/target_follow/goal_odom'), latched)
        self.status = self.create_publisher(String, p('status_topic', '/target_follow/status'), 10)
        self.client = self.create_client(SetParametersAtomically,
            p('follow_parameter_service', '/uwb_follow_controller_node/set_parameters_atomically'))
        self.create_subscription(Odometry, p('odom_topic', '/odom'), self.on_odom, qos_profile_sensor_data)
        if self.kind == 'uwb':
            from robot_local_motion.msg import TargetObservation
            self.create_subscription(TargetObservation, p('observation_topic', '/robot_local_motion/target'),
                                     self.on_uwb, qos_profile_sensor_data)
        elif self.kind == 'vision':
            self.create_subscription(String, p('vision_topic', '/perception/vision/object_detections'), self.on_vision, qos_profile_sensor_data)
            self.create_subscription(Image, p('depth_topic', '/camera/camera/aligned_depth_to_color/image_raw'),
                                     self.depths.append, qos_profile_sensor_data)
            self.create_subscription(CameraInfo, p('camera_info_topic', '/camera/camera/color/camera_info'),
                                     self.on_info, qos_profile_sensor_data)
        else:
            self.create_subscription(PointStamped, p('point_topic', '/target_follow/point'), self.on_point, qos_profile_sensor_data)
        self.create_service(Trigger, '~/start', self.start)
        self.create_service(Trigger, '~/cancel', self.cancel)
        self.create_timer(.05, self.tick)
        self.create_timer(.5, self.emit)

    def start(self, request, response):
        self.goal = self.pending = None
        self.vision_message = None
        self.armed = True
        self.reset_requested = self.manage
        self.message = ''
        response.success, response.message = True, 'waiting for a new target'
        return response

    def cancel(self, request, response):
        self.armed = False
        self.reset_requested = False
        self.goal = self.pending = None
        self.vision_message = None
        response.success, response.message = True, 'target cleared; original tracking pause requested'
        return response

    def on_info(self, msg):
        self.info = msg

    def on_odom(self, msg):
        if msg.header.frame_id == self.odom_frame:
            self.odom = msg

    def on_uwb(self, msg):
        if msg.valid and msg.source == self.source and (not self.tag or msg.target_id == self.tag):
            self.on_point(PointStamped(header=msg.header, point=msg.position))

    def on_point(self, msg):
        if not self.armed or (self.mode == 'fixed' and self.goal is not None):
            return
        if self.mode == 'stream':
            if not self.manage or (self.applied is True and not self.reset_requested):
                self.output.publish(msg)  # Live input retains the producer's stamp.
        elif self.pending is None:
            self.pending = msg

    def on_vision(self, msg):
        if not self.armed or self.goal is not None or self.pending is not None:
            return
        self.vision_message = msg
        try:
            packet = json.loads(msg.data)
            if packet.get('status', 'ok') != 'ok':
                return
            for item in packet.get('objects', []):
                if self.label and item.get('label') != self.label:
                    continue
                if self.vision_id and item.get('target_id') != self.vision_id:
                    continue
                if item.get('tracking_state', 'tracking') != 'tracking':
                    continue
                header = item.get('header', packet.get('header', {}))
                stamp = float(header['stamp'])
                point = PointStamped()
                point.header.stamp = Time(nanoseconds=round(stamp*1e9)).to_msg()
                pose = item.get('pose_3d', {})
                if 'pose_3d' in item and not pose.get('valid'):
                    continue  # Retain the existing Vision producer's validity decision.
                if pose.get('valid'):
                    # Reuse Vision's existing bbox/depth fusion when supplied.
                    point.header.frame_id = pose['frame_id']
                    xyz = tuple(float(pose[k]) for k in ('x', 'y', 'z'))
                else:
                    if self.info is None or not self.depths:
                        return
                    depth = min(self.depths, key=lambda d: abs(Time.from_msg(d.header.stamp).nanoseconds/1e9-stamp))
                    delta = abs(Time.from_msg(depth.header.stamp).nanoseconds/1e9-stamp)
                    if delta > self.sync_delta:
                        return
                    if (depth.header.frame_id != self.info.header.frame_id
                            or (depth.width, depth.height) != (self.info.width, self.info.height)
                            or header.get('frame_id') != depth.header.frame_id):
                        raise ValueError('bbox, registered depth and intrinsics must describe the same optical image')
                    point.header.frame_id = depth.header.frame_id
                    xyz = bbox_point(item['bbox'], depth, self.info, self.radius)
                point.point.x, point.point.y, point.point.z = xyz
                self.on_point(point)
                break
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, struct.error) as exc:
            self.message = str(exc)

    def tick(self):
        if self.manage:
            if self.future is not None and self.future.done():
                try:
                    result = self.future.result().result
                    if result.successful:
                        self.applied = self.sent
                        if not self.sent:
                            self.reset_requested = False
                    else:
                        self.message = result.reason
                except Exception as exc:
                    self.message = str(exc)
                self.future = None
            desired = self.armed and not self.reset_requested
            if self.future is None and (self.applied != desired or self.reset_requested) and self.client.service_is_ready():
                self.sent = desired
                request = SetParametersAtomically.Request(parameters=[
                    Parameter('tracking_enabled', value=self.sent).to_parameter_msg()])
                self.future = self.client.call_async(request)
        if not self.armed or self.mode != 'fixed':
            return
        if self.kind == 'vision' and self.vision_message is not None and self.goal is None and self.pending is None:
            self.on_vision(self.vision_message)
        if self.pending is not None:
            try:
                msg = self.pending
                stamp = Time.from_msg(msg.header.stamp)
                if stamp.nanoseconds <= 0 or not msg.header.frame_id:
                    raise ValueError('fixed target requires an observation stamp and frame')
                xyz = msg.point.x, msg.point.y, msg.point.z
                if not all(math.isfinite(v) for v in xyz):
                    raise ValueError('target XYZ must be finite')
                if msg.header.frame_id != self.odom_frame:
                    tf = self.tf.lookup_transform(self.odom_frame, msg.header.frame_id, stamp)
                    xyz = transform_point(tf.transform, xyz)
                self.goal = PointStamped()
                self.goal.header.stamp, self.goal.header.frame_id = msg.header.stamp, self.odom_frame
                self.goal.point.x, self.goal.point.y, self.goal.point.z = xyz
                self.pending = None
                self.fixed_output.publish(self.goal)
                self.message = ''
            except TransformException as exc:
                self.message = str(exc)  # Wait for the transform at the observation's actual stamp.
            except ValueError as exc:
                self.pending = None
                self.message = str(exc)
        if self.goal is None or self.odom is None or (self.manage and (self.applied is not True or self.reset_requested)):
            return
        stamp = Time.from_msg(self.odom.header.stamp)
        if stamp.nanoseconds <= self.published_ns:
            return
        try:
            tf = self.tf.lookup_transform(self.base, self.odom_frame, stamp)
            p = self.goal.point
            xyz = transform_point(tf.transform, (p.x, p.y, p.z))
            point = PointStamped()
            point.header.stamp, point.header.frame_id = self.odom.header.stamp, self.base
            point.point.x, point.point.y, point.point.z = xyz
            self.output.publish(point)
            self.published_ns = stamp.nanoseconds
            self.message = ''
        except TransformException as exc:
            self.message = str(exc)

    def emit(self):
        p = self.goal.point if self.goal else None
        self.status.publish(String(data=json.dumps(dict(armed=self.armed, tracking_enabled=self.applied, input_mode=self.mode,
            input_kind=self.kind, goal_odom=[p.x, p.y, p.z] if p else None,
            goal_stamp_ns=Time.from_msg(self.goal.header.stamp).nanoseconds if p else None,
            message=self.message))))


def main():
    rclpy.init()
    node = FollowInput()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
