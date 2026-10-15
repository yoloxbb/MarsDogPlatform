#!/usr/bin/env python3
"""Read-only verification against an already started official bridge; no control RPCs."""
import argparse
import json
import math
import time

import rclpy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, BatteryState
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger
from uniubi_motion_bridge.msg import MotionStatus
from uniubi_motion_bridge.srv import JsonCommand

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=float, default=15)
parser.add_argument('--output')
args = parser.parse_args()
rclpy.init()
node = rclpy.create_node('lingmao_readonly_verification')
counts = dict(odom=0, imu=0, battery=0, status=0)
last = {}

def receive(kind, message):
    counts[kind] += 1
    if kind == 'odom':
        last[kind] = dict(frame_id=message.header.frame_id, child_frame_id=message.child_frame_id,
                          stamp_sec=message.header.stamp.sec,
                          x=message.pose.pose.position.x, y=message.pose.pose.position.y)
    elif kind == 'imu':
        last[kind] = dict(frame_id=message.header.frame_id)
    elif kind == 'battery':
        last[kind] = {key: value if math.isfinite(value) else None
                      for key, value in [('voltage', message.voltage), ('percentage', message.percentage)]}
    else:
        # Never dump arbitrary status/RPC payloads or credentials into logs.
        last[kind] = {'control_state': int(message.control_state),
                      'current_action': message.current_action,
                      'last_error_code': int(message.last_error_code)}

subscriptions = []
for kind, topic, interface in [('odom', '/odom', Odometry), ('imu', '/imu/data', Imu),
                                ('battery', '/battery_state', BatteryState),
                                ('status', '/motion/status', MotionStatus)]:
    subscriptions.append(node.create_subscription(interface, topic,
        lambda message, kind=kind: receive(kind, message), qos_profile_sensor_data))
queries = {}
try:
    for name, interface in [('/motion/query_capabilities', Trigger),
                             ('/motion/query_system_status', JsonCommand),
                             ('/motion/query_state', JsonCommand)]:
        client = node.create_client(interface, name)
        if not client.wait_for_service(timeout_sec=5):
            queries[name] = {'success': False, 'reason': 'service unavailable'}
            continue
        future = client.call_async(interface.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=10)
        if not future.done() or future.result() is None:
            queries[name] = {'success': False, 'reason': 'RPC timeout'}
        else:
            response = future.result()
            queries[name] = {'success': response.success}
            if hasattr(response, 'error_code'):
                queries[name]['error_code'] = response.error_code
    until = time.monotonic() + args.seconds
    while time.monotonic() < until:
        rclpy.spin_once(node, timeout_sec=0.1)
    passed = all(value['success'] for value in queries.values()) and counts['status'] > 0 and counts['imu'] > 0
    report = {'status': 'PASS' if passed else 'INCOMPLETE', 'queries': queries,
              'message_counts': counts, 'last_samples': last,
              'navigation_odom_available': counts['odom'] > 0 and
                  last.get('odom', {}).get('frame_id') == 'odom' and
                  last.get('odom', {}).get('child_frame_id') == 'base_link',
              'scope': 'Read-only RPC and observations; no control acquisition, action or cmd_vel publishing.'}
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    print(text)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(text + '\n', encoding='utf-8')
finally:
    node.destroy_node()
    rclpy.shutdown()
raise SystemExit(0 if passed else 1)
