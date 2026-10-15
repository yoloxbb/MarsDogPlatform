"""Opt-in data-only multi-beacon UWB input. Never publishes robot velocity."""
from collections import Counter
from dataclasses import asdict
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import select
import termios
import time

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from geometry_msgs.msg import PointStamped
from robot_local_motion.msg import TargetObservation
from uwb_aoa_pkg.msg import LibAoaRobotMsg
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from .uwb_protocol import C5Decoder, canonical_id
from .uwb_tracking import BeaconTracker, TrackingConfig


class UwbMultiTagInput(Node):
    def __init__(self, **kwargs):
        super().__init__('uwb_multitag_input', **kwargs)
        def param(name, default):
            return self.declare_parameter(name, default, ParameterDescriptor(read_only=True)).value
        self.enabled = param('enable_serial', False)
        self.port = param('port', '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AG00S82A-if00-port0')
        ids = [canonical_id(x) for x in param('beacon_ids', ['0x87654322', '0x87654324'])]
        aliases = param('target_ids', ['0x87654322', '0x87654324'])
        if not ids or len(ids) != len(set(ids)) or len(ids) != len(aliases) or not all(aliases) or len(aliases) != len(set(aliases)):
            raise ValueError('beacon_ids and target_ids must be equal-sized, nonempty, unique lists')
        if len(ids) > 32:
            raise ValueError('at most 32 explicitly configured beacons')
        self.aliases = dict(zip(ids, aliases))
        self.source = param('source', 'uwb_multitag')
        self.frame = param('sensor_frame', 'uwb_link')
        if not self.source or not self.frame:
            raise ValueError('source and sensor_frame are mandatory')
        self.rate = param('publish_rate_hz_per_tag', 10.0)
        self.angle_sign = param('angle_sign', -1.0)
        self.angle_offset = param('angle_offset_rad', 0.0)
        if not math.isfinite(self.rate) or not 0 < self.rate <= 200 or self.angle_sign not in (-1.0, 1.0) or not math.isfinite(self.angle_offset):
            raise ValueError('invalid publication rate or angle convention')
        base = TrackingConfig(**{k: param(k, v) for k, v in asdict(TrackingConfig()).items()})
        overrides = json.loads(param('tag_overrides_json', '{}'))
        if not isinstance(overrides, dict):
            raise ValueError('tag_overrides_json must be an object')
        overrides = {canonical_id(k): v for k, v in overrides.items()}
        if set(overrides) - set(ids):
            raise ValueError('tag overrides contain an unconfigured beacon ID')
        self.trackers = {}
        for identity in ids:
            values = overrides.get(identity, {})
            if not isinstance(values, dict) or set(values) - set(asdict(base)):
                raise ValueError('unknown or invalid per-tag tracking override')
            cfg = TrackingConfig(**{**asdict(base), **values})
            self.trackers[identity] = BeaconTracker(cfg, self.angle_sign, self.angle_offset)
        self.decoder = C5Decoder(param('allow_observed_len33', True))
        target_topic = param('target_topic', '/robot_local_motion/target')
        raw_topic = param('raw_topic', '/uwb/multitag/raw')
        diagnostic_topic = param('diagnostics_topic', '/uwb/multitag/diagnostics')
        self.pub = self.create_publisher(TargetObservation, target_topic, 100)
        self.raw_pub = self.create_publisher(LibAoaRobotMsg, raw_topic, 100)
        self.diag_pub = self.create_publisher(DiagnosticArray, diagnostic_topic, 10)
        self.legacy_id = param('legacy_target_id', '')
        self.legacy_frame = param('legacy_target_frame', 'base_footprint')
        self.legacy_pub = None
        if self.legacy_id:
            if self.legacy_id not in aliases or not self.legacy_frame:
                raise ValueError('legacy_target_id must select exactly one configured target alias')
            self.legacy_pub = self.create_publisher(PointStamped, param('legacy_point_topic', '/uwb/target_point'), 10)
            self.tf = Buffer()
            self.tf_listener = TransformListener(self.tf, self)
        else:
            param('legacy_point_topic', '/uwb/target_point')
        if self.enabled and self.get_parameter('use_sim_time').value:
            raise ValueError('physical serial input requires a running wall clock')
        self.fd = None
        self.old_attrs = None
        self.next_open = 0.0
        self.sequence = {identity: time.time_ns() for identity in ids}
        self.last_stamp, self.next_publish = {}, {}
        self.counters = Counter()
        self.connection = 'disabled' if not self.enabled else 'waiting'
        self.timer = self.create_timer(0.01, self.tick)
        self.diag_timer = self.create_timer(1.0, self.diagnostics)

    def open_serial(self):
        # Legacy drivers do not take flock: check their ownership before changing termios.
        busy = subprocess.run(['fuser', self.port], capture_output=True, timeout=2)
        if busy.returncode != 1:
            raise OSError('serial is occupied or ownership check failed')
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        exclusive = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.ioctl(fd, termios.TIOCEXCL)
            exclusive = True
            old = termios.tcgetattr(fd)
            attrs = termios.tcgetattr(fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIFLUSH)
            self.old_attrs, self.fd = old, fd
            self.poller = select.poll()
            self.poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
            self.decoder.reset()
            for identity, tracker in self.trackers.items():
                tracker.reset()
                self.next_publish.pop(identity, None)
            self.connection = 'connected'
            self.get_logger().info('UWB multi-tag serial connected; data outputs only')
        except Exception:
            if exclusive:
                fcntl.ioctl(fd, termios.TIOCNXCL)
            os.close(fd)
            raise

    def close_serial(self):
        if self.fd is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.old_attrs)
            except OSError:
                pass
            try:
                fcntl.ioctl(self.fd, termios.TIOCNXCL)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None

    def invalidate(self, identity, reason):
        if identity in self.last_stamp:
            self.publish(identity, self.last_stamp[identity], False, 0.0, 0.0)
        self.trackers[identity].valid = False
        self.trackers[identity].reason = reason

    def tick(self):
        now = time.monotonic()
        if self.enabled and self.fd is None and now >= self.next_open:
            try:
                self.open_serial()
            except (OSError, subprocess.SubprocessError) as exc:
                self.next_open = now + 2.0
                self.connection = str(exc)
        if self.fd is not None:
            try:
                events = self.poller.poll(0)
                if any(flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL) for _, flags in events):
                    raise OSError('UWB serial disconnected')
                for _ in range(4):
                    if not events:
                        break
                    try:
                        data = os.read(self.fd, 4096)
                    except BlockingIOError:
                        break
                    if not data:
                        # VMIN=0 permits an empty read when there is no input.
                        break
                    for frame in self.decoder.feed(data, time.monotonic()):
                        self.observe(frame, time.monotonic(), self.get_clock().now().to_msg())
            except OSError as exc:
                for identity in self.trackers:
                    self.invalidate(identity, 'serial_disconnected')
                self.close_serial()
                self.decoder.reset()
                self.next_open = now + 2.0
                self.connection = str(exc)
        for identity, tracker in self.trackers.items():
            if tracker.expire(now) is not None:
                self.invalidate(identity, 'expired')

    def observe(self, frame, now, stamp):
        identity = canonical_id(frame.fob_id)
        if identity not in self.trackers:
            self.counters['unknown_id'] += 1
            return
        result = self.trackers[identity].update(frame, now)
        if result is None:
            return
        self.last_stamp[identity] = stamp
        self.publish_raw(frame, stamp)
        if not result.valid:
            self.publish(identity, stamp, False, result.x, result.y)
        elif now >= self.next_publish.get(identity, now):
            # Independent phase accumulators prevent the 10.4 Hz wire rate being halved.
            self.next_publish[identity] = max(self.next_publish.get(identity, now) + 1.0 / self.rate, now)
            self.publish(identity, stamp, True, result.x, result.y)

    def publish(self, identity, stamp, valid, x, y):
        self.sequence[identity] += 1
        msg = TargetObservation()
        msg.header.stamp, msg.header.frame_id = stamp, self.frame
        msg.source, msg.target_id = self.source, self.aliases[identity]
        msg.sequence, msg.valid = self.sequence[identity], valid
        msg.position.x, msg.position.y = x, y
        msg.confidence = 1.0 if valid else 0.0  # Transport/filter validity, not measured accuracy.
        self.pub.publish(msg)
        if self.legacy_pub is not None and valid and msg.target_id == self.legacy_id:
            point = PointStamped()
            point.header, point.point = msg.header, msg.position
            if self.legacy_frame != self.frame:
                try:
                    transform = self.tf.lookup_transform(self.legacy_frame, self.frame, Time.from_msg(stamp))
                    from .server import transform_point
                    point.point.x, point.point.y = transform_point(x, y, 0.0, transform.transform)
                    point.header.frame_id = self.legacy_frame
                except Exception:
                    self.counters['legacy_tf_missing'] += 1
                    return
            self.legacy_pub.publish(point)

    def publish_raw(self, frame, stamp):
        msg = LibAoaRobotMsg()
        msg.header.stamp, msg.header.frame_id = stamp, self.frame
        msg.fob_id, msg.fob_type, msg.sync_cnt = frame.fob_id, frame.fob_type, frame.sync_count
        msg.raw_distance, msg.raw_angle, msg.raw_pitch = frame.distance, frame.angle_deg, frame.pitch_deg
        yaw = (self.angle_sign * math.radians(frame.angle_deg) + self.angle_offset
               if math.isfinite(frame.angle_deg) else math.nan)
        msg.r, msg.a = frame.distance, yaw
        msg.x, msg.y = frame.distance * math.cos(yaw), frame.distance * math.sin(yaw)
        msg.state = 0  # Unfused wire measurement; never claim SDK state=1.
        msg.pos_confidence = frame.confidence
        msg.rssi = list(frame.rssi)
        msg.rx_power, msg.rssi_fpp, msg.rssi_np, msg.rssi_ble = frame.rx_power, frame.rssi_fpp, frame.rssi_np, frame.rssi_ble
        self.raw_pub.publish(msg)

    def diagnostics(self):
        array = DiagnosticArray()
        array.header.stamp = self.get_clock().now().to_msg()
        for identity, tracker in self.trackers.items():
            status = DiagnosticStatus()
            status.name, status.hardware_id = 'uwb_multitag/' + self.aliases[identity], identity
            status.level = DiagnosticStatus.OK if tracker.valid else DiagnosticStatus.WARN
            status.message = tracker.reason
            values = {'connection': self.connection, 'source': self.source, 'sensor_frame': self.frame,
                      'sequence': self.sequence[identity], 'valid': tracker.valid,
                      'confidence_semantics': 'transport_and_filter_validity_only',
                      'raw_confidence_semantics': 'unverified_extension_byte_for_len33',
                      'tracker': dict(tracker.counters), 'parser': dict(self.decoder.counters),
                      'node': dict(self.counters), 'settings': asdict(tracker.config)}
            status.values = [KeyValue(key=k, value=json.dumps(v)) for k, v in values.items()]
            array.status.append(status)
        self.diag_pub.publish(array)

    def destroy_node(self):
        self.close_serial()
        return super().destroy_node()


def main():
    rclpy.init()
    node = None
    try:
        node = UwbMultiTagInput()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
