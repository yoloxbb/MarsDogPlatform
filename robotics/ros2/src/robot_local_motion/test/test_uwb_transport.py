"""Synthetic PTY + real DDS. No physical serial device or chassis is used."""
import copy
import math
import os
import threading
import time
import pytest
from uwb_test_support import packet
pytest.importorskip('rclpy')
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.executors import SingleThreadedExecutor
from robot_local_motion.msg import TargetObservation
from geometry_msgs.msg import PointStamped
from robot_local_motion_runtime.uwb_serial import UwbMultiTagInput
from robot_local_motion_runtime.server import LocalMotionServer


def test_serial_identity_filter_legacy_selection_and_independent_revocation():
    assert os.environ.get('ROS_DOMAIN_ID') == '225' and os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    rclpy.init()
    master, slave = os.openpty()
    port = os.ttyname(slave); os.close(slave)
    params = {'enable_serial':True, 'port':port, 'target_topic':'/test/uwb/target',
              'raw_topic':'/test/uwb/raw', 'diagnostics_topic':'/test/uwb/diagnostics',
              'legacy_target_id':'0x87654322', 'legacy_target_frame':'uwb_link',
              'legacy_point_topic':'/test/uwb/legacy', 'acquire_samples':1,
              'smoothing_tau_sec':0.0, 'stale_timeout_sec':0.3}
    node = UwbMultiTagInput(parameter_overrides=[Parameter(k,value=v) for k,v in params.items()])
    observer = Node('uwb_transport_observer')
    rows, points = [], []
    observer.create_subscription(TargetObservation,'/test/uwb/target',rows.append,100)
    observer.create_subscription(PointStamped,'/test/uwb/legacy',points.append,100)
    executor = SingleThreadedExecutor(); executor.add_node(node); executor.add_node(observer)
    thread = threading.Thread(target=executor.spin); thread.start()
    try:
        end=time.monotonic()+4
        while node.fd is None and time.monotonic()<end:time.sleep(.02)
        assert node.fd is not None
        with pytest.raises(OSError):node.open_serial()
        # Wait for DDS discovery; interleave widely separated coordinates.
        time.sleep(.4)
        for i in range(1,9):
            os.write(master,packet(sync=i,distance=2)+packet(identity=0x87654324,sync=i,distance=8,angle=180))
            time.sleep(.1)
        assert {m.target_id for m in rows if m.valid} == {'0x87654322','0x87654324'}
        assert all(abs(m.position.x-(2 if m.target_id.endswith('22') else -8)) < 1e-5 for m in rows if m.valid)
        assert points and all(abs(m.point.x-2)<1e-5 for m in points)
        assert not node.trackers['0x87654324'].counters['jump_rejected']
        # Expire only A, while B continues to receive fresh samples.
        for i in range(9,16):
            os.write(master,packet(identity=0x87654324,sync=i,distance=8,angle=180));time.sleep(.1)
        assert not node.trackers['0x87654322'].valid
        assert node.trackers['0x87654324'].valid
        assert any(not m.valid and m.target_id.endswith('22') for m in rows)
        # Simulate A restarting its firmware counter after the independent timeout.
        for i in range(1,7):
            os.write(master,packet(sync=i,distance=2)+packet(identity=0x87654324,sync=15+i,distance=8,angle=180))
            time.sleep(.1)
        assert node.trackers['0x87654322'].valid and node.trackers['0x87654324'].valid
        assert node.trackers['0x87654322'].counters['wire_clock_reset']==1
        sequences={}
        for m in rows:
            assert m.sequence > sequences.get(m.target_id,0)
            sequences[m.target_id]=m.sequence
    finally:
        executor.shutdown();thread.join(timeout=3)
        node.destroy_node();observer.destroy_node();os.close(master);rclpy.shutdown()


def test_consumer_ignores_old_revocations_and_invalidates_only_selected_id():
    assert os.environ.get('ROS_DOMAIN_ID') == '225' and os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    rclpy.init();server=LocalMotionServer()
    try:
        a=TargetObservation();a.source='test';a.target_id='a';a.header.frame_id='odom'
        a.header.stamp=server.get_clock().now().to_msg();a.sequence=1;a.valid=True;a.confidence=1.0;a.position.x=2.0
        b=copy.deepcopy(a);b.target_id='b';b.position.x=8.0
        server.on_target(a);server.on_target(b)
        old=copy.deepcopy(a);old.valid=False;server.on_target(old)
        assert server.targets[('test','a')].x==2.0
        revoked=copy.deepcopy(a);revoked.sequence=2;revoked.valid=False
        server.on_target(revoked)
        assert server.targets[('test','a')] is None and server.targets[('test','b')].x==8.0
        fresh=copy.deepcopy(a);fresh.sequence=3;fresh.header.stamp=server.get_clock().now().to_msg()
        server.on_target(fresh);server.on_target(revoked)
        assert server.targets[('test','a')].x==2.0
    finally:server.destroy_node();rclpy.shutdown()
