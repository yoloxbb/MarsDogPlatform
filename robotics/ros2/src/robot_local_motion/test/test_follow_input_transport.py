"""New target adapters over the real, unchanged C++ follow/planner chain."""
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import threading
import time
import pytest

pytest.importorskip('rclpy')
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import PointStamped, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import Header, String
from std_srvs.srv import Trigger
from tf2_ros import StaticTransformBroadcaster
from robot_local_motion_runtime.follow_input import FollowInput
from robot_local_motion_runtime.behavior_odom_input import BehaviorOdomInput, convert_odom
from test_task_transport import World, stop_owned_planner
from test_roundtrip_transport import until


@pytest.fixture
def stack(request, tmp_path):
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1' and os.environ.get('ROS_DOMAIN_ID') == '224'
    from ament_index_python.packages import get_package_share_directory as share
    own, old = Path(share('robot_local_motion')), Path(share('go2_uwb_local_follow'))
    rclpy.init()
    mode, kind = request.param
    adapter = FollowInput(parameter_overrides=[Parameter('input_mode', value=mode),
        Parameter('input_kind', value=kind), Parameter('autostart', value=True),
        Parameter('odom_topic', value='/test/odom')])
    world = World()
    points = []
    world.create_subscription(PointStamped, '/target_follow/selected_target', points.append, 10)
    processes, logs = [], []
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(world);executor.add_node(adapter)
    thread = threading.Thread(target=executor.spin)
    configs = [('uwb_follow_controller_node', 'uwb_follow_only.yaml', {
        'enable_motion': 'false', 'tracking_enabled': 'false', 'odom_topic': '/test/odom',
        'target_topic': '/target_follow/selected_target', 'cmd_vel_topic': '/test/debug',
        'nominal_cmd_topic': '/robot_local_motion/nominal_cmd', 'follow_distance': '0.0' if (mode,kind) == ('fixed','point') else '0.8',
        'min_linear_speed': '0.10'}),
      ('local_velocity_planner_node', 'local_velocity_planner.yaml', {
        'enable_motion': 'true', 'odom_topic': '/test/odom', 'odom_child_frame': 'base_footprint',
        'obstacle_topic': '/test/cloud', 'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
        'final_cmd_topic': '/robot_local_motion/final_cmd', 'cmd_vel_topic': '/test/cmd_vel',
        'min_linear_speed': '0.10'})]
    try:
        for executable, config, params in configs:
            log = (tmp_path/(executable+'.log')).open('w');logs.append(log)
            args = ['ros2', 'run', 'go2_uwb_local_follow', executable, '--ros-args',
                '--params-file', str(old/'config'/config), '--params-file', str(own/'config/lingmao_roundtrip.yaml')]
            for key, value in params.items():args += ['-p', key+':='+value]
            processes.append(subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        thread.start()
        until(lambda: adapter.applied is True and adapter.odom is not None, 8)
        time.sleep(.5)
        yield world, adapter, points
    finally:
        adapter.armed = False
        until(lambda: adapter.applied is False, 4)
        for process in processes:stop_owned_planner(process)
        executor.shutdown()
        if thread.ident:thread.join(timeout=5);assert not thread.is_alive()
        adapter.destroy_node();world.destroy_node();rclpy.shutdown()
        for log in logs:log.close()


def point(world, x, frame='base_footprint'):
    msg = PointStamped(header=Header(stamp=rclpy.time.Time(
        nanoseconds=world.get_clock().now().nanoseconds-50000000).to_msg(), frame_id=frame))
    msg.point.x = x
    return msg


@pytest.mark.parametrize('stack', [('stream', 'point')], indirect=True)
def test_stream_keeps_observation_stamp_and_original_target_loss_stop(stack):
    world, adapter, points = stack
    pub = world.create_publisher(PointStamped, '/target_follow/point', 10)
    until(lambda: pub.get_subscription_count() > 0, 3)
    sample = point(world, 3.)
    pub.publish(sample)
    until(lambda: len(points) > 0, 3)
    assert points[-1].header == sample.header
    until(lambda: len(world.commands) > 5 and world.v > .01, 2)
    until(lambda: abs(world.v) < 1e-6 and abs(world.w) < 1e-6, 3)
    assert len(points) == 1  # A stale observation is never refreshed by the adapter.


@pytest.mark.parametrize('stack', [('fixed', 'point')], indirect=True)
def test_one_point_stays_in_odom_while_robot_moves_then_original_follow_stops(stack):
    world, adapter, points = stack
    pub = world.create_publisher(PointStamped, '/target_follow/point', 10)
    until(lambda: pub.get_subscription_count() > 0, 3)
    pub.publish(point(world, 2.5))
    until(lambda: adapter.goal is not None, 3)
    saved = adapter.goal.point.x
    assert saved == pytest.approx(2.5, abs=.02)
    until(lambda: world.x > .5, 8)
    pub.publish(point(world, 8.))
    time.sleep(.3)
    assert adapter.goal.point.x == saved
    assert points[-1].point.x < points[0].point.x-.3
    until(lambda: world.x > 2.35 and abs(world.v) < 1e-6, 20)
    assert saved-world.x <= .10
    assert world.count_publishers('/test/cmd_vel') == 1
    world.inputs = False
    time.sleep(.3)
    count = len(points)
    time.sleep(.6)
    assert len(points) == count  # No fresh relative target without fresh odometry/TF.
    world.inputs = True
    client = world.create_client(Trigger, '/target_follow_input/cancel')
    until(client.service_is_ready, 3)
    future = client.call_async(Trigger.Request())
    until(future.done, 3)
    assert future.result().success
    until(lambda: adapter.applied is False, 3)
    assert adapter.goal is None
    world.destroy_client(client)
    client = world.create_client(Trigger, '/target_follow_input/start')
    until(client.service_is_ready, 3)
    future = client.call_async(Trigger.Request())
    until(future.done, 3)
    assert future.result().success
    pub.publish(point(world, 1.5))
    until(lambda: adapter.goal is not None and adapter.applied is True and not adapter.reset_requested, 4)
    assert adapter.goal.point.x > saved+1.
    world.destroy_client(client)


@pytest.mark.parametrize('stack', [('fixed', 'vision')], indirect=True)
def test_existing_vision_pose_3d_is_reused_without_requiring_second_depth_fusion(stack):
    world, adapter, points = stack
    pub = world.create_publisher(String, '/perception/vision/object_detections', qos_profile_sensor_data)
    until(lambda: pub.get_subscription_count() > 0, 3)
    packet = dict(status='ok', header=dict(stamp=world.get_clock().now().nanoseconds/1e9, frame_id='odom'),
        objects=[dict(label='ball', pose_3d=dict(valid=True, frame_id='odom', x=2.2, y=.3, z=.1))])
    pub.publish(String(data=json.dumps(packet)))
    until(lambda: adapter.goal is not None, 3)
    assert len(adapter.depths) == 0
    assert adapter.goal.point.x == 2.2 and adapter.goal.point.y == .3


@pytest.mark.parametrize('stack', [('fixed', 'vision')], indirect=True)
def test_bbox_depth_optical_projection_latches_once_in_odom(stack):
    world, adapter, points = stack
    broadcaster = StaticTransformBroadcaster(world)
    tf = TransformStamped(header=Header(stamp=world.get_clock().now().to_msg(), frame_id='base_footprint'),
                          child_frame_id='test_optical')
    tf.transform.translation.x, tf.transform.translation.z = .2, .4
    tf.transform.rotation.x, tf.transform.rotation.y, tf.transform.rotation.z, tf.transform.rotation.w = -.5, .5, -.5, .5
    broadcaster.sendTransform(tf)
    info_pub = world.create_publisher(CameraInfo, '/camera/camera/color/camera_info', qos_profile_sensor_data)
    depth_pub = world.create_publisher(Image, '/camera/camera/aligned_depth_to_color/image_raw', qos_profile_sensor_data)
    vision_pub = world.create_publisher(String, '/perception/vision/object_detections', 10)
    until(lambda: vision_pub.get_subscription_count() > 0 and info_pub.get_subscription_count() > 0, 3)
    stamp = world.get_clock().now()
    header = Header(stamp=stamp.to_msg(), frame_id='test_optical')
    info = CameraInfo(header=header, width=5, height=5, k=[4.,0.,2.,0.,4.,2.,0.,0.,1.])
    depth = Image(header=header, width=5, height=5, encoding='16UC1', step=10, data=struct.pack('<25H', *([2000]*25)))
    info_pub.publish(info);depth_pub.publish(depth)
    until(lambda: adapter.info is not None and len(adapter.depths) > 0, 3)
    packet = dict(header=dict(stamp=stamp.nanoseconds/1e9, frame_id='test_optical'), status='ok',
                  objects=[dict(label='ball', bbox=[.25,.25,.5,.5])])
    vision_pub.publish(String(data=json.dumps(packet)))
    until(lambda: adapter.goal is not None, 3)
    assert adapter.goal.point.x == pytest.approx(2.2, abs=.02)
    assert adapter.goal.point.y == pytest.approx(0., abs=.02)
    assert adapter.goal.point.z == pytest.approx(.4)
    packet['objects'][0]['pose_3d'] = dict(valid=True, frame_id='odom', x=9., y=0., z=0.)
    vision_pub.publish(String(data=json.dumps(packet)))
    time.sleep(.3)
    assert adapter.goal.point.x == pytest.approx(2.2, abs=.02)


def test_behavior_odom_reference_includes_offset_rotation_and_lever_velocity():
    msg = Odometry(child_frame_id='base_link')
    msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(math.pi/4), math.cos(math.pi/4)
    msg.twist.twist.angular.z = 1.
    tf = TransformStamped().transform
    tf.rotation.w, tf.translation.x = 1., .2
    result = convert_odom(msg, tf, 'base_footprint')
    assert result.pose.pose.position.y == pytest.approx(.2)
    assert result.twist.twist.linear.y == pytest.approx(.2)
    assert result.header == msg.header and result.child_frame_id == 'base_footprint'


def test_existing_circle_freezes_uwb_center_and_cancels_with_one_final_publisher(tmp_path):
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1' and os.environ.get('ROS_DOMAIN_ID') == '224'
    from ament_index_python.packages import get_package_share_directory as share
    from geometry_msgs.msg import PoseStamped
    from rclpy.action import ActionClient
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from go2_uwb_behavior.action import RandomRoam
    from test_roundtrip_transport import DualWorld
    from test_task_transport import wait
    rclpy.init()
    old = Path(share('go2_uwb_local_follow'))
    behavior = Path(share('go2_uwb_behavior'))
    world = DualWorld();world.owner_x = 3.;world.frisbee_enabled = False
    adapter = FollowInput(parameter_overrides=[Parameter('input_kind', value='uwb'),
        Parameter('target_id', value='0x87654322'), Parameter('manage_tracking', value=False),
        Parameter('autostart', value=True), Parameter('odom_topic', value='/test/odom')])
    odom = BehaviorOdomInput(parameter_overrides=[Parameter('odom_topic', value='/test/odom')])
    centers = []
    world.create_subscription(PoseStamped, '/motion/random_roam/play_center', centers.append,
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    executor = MultiThreadedExecutor(num_threads=3)
    for node in (world, adapter, odom):executor.add_node(node)
    thread = threading.Thread(target=executor.spin)
    client = ActionClient(world, RandomRoam, '/motion/random_roam')
    processes, logs, goal = [], [], None
    specs = [('go2_uwb_local_follow', 'local_velocity_planner_node', old/'config/local_velocity_planner.yaml', {
        'enable_motion': 'true', 'odom_topic': '/test/odom', 'odom_child_frame': 'base_link',
        'obstacle_topic': '/test/cloud', 'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
        'cmd_vel_topic': '/test/play_planner', 'diagnostics_topic': '/robot_local_motion/planner_diagnostics',
        'min_linear_speed': '0.10'}),
      ('go2_uwb_behavior', 'uwb_behavior_controller_node', behavior/'config/behavior_controller.yaml', {
        'enable_motion': 'true', 'target_topic': '/target_follow/selected_target',
        'odom_topic': '/target_follow/behavior_odom', 'obstacle_topic': '/test/cloud',
        'nominal_cmd_topic': '/robot_local_motion/nominal_cmd', 'planner_cmd_topic': '/test/play_planner',
        'planner_diagnostics_topic': '/robot_local_motion/planner_diagnostics', 'cmd_vel_topic': '/test/cmd_vel',
        'min_linear_speed': '0.10'})]
    try:
        for package, executable, config, params in specs:
            log = (tmp_path/(executable+'.log')).open('w');logs.append(log)
            args = ['ros2', 'run', package, executable, '--ros-args', '--params-file', str(config)]
            for key,value in params.items():args += ['-p', key+':='+value]
            processes.append(subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        thread.start()
        assert client.wait_for_server(timeout_sec=8)
        time.sleep(.8)
        goal = wait(client.send_goal_async(RandomRoam.Goal(random_seed=7, timeout_sec=30., min_radius=.5, max_radius=2.)))
        assert goal.accepted
        result = goal.get_result_async()
        until(lambda: len(centers) > 0, 4)
        center = centers[-1].pose.position.x
        assert center == pytest.approx(3., abs=.05)
        world.owner_x = 5.
        time.sleep(.5)
        assert centers[-1].pose.position.x == center
        assert world.count_publishers('/test/cmd_vel') == 1
        wait(goal.cancel_goal_async())
        assert wait(result, 5).result.code == RandomRoam.Result.CANCELED
    finally:
        if goal is not None and goal.accepted and not result.done():
            wait(goal.cancel_goal_async())
            wait(result, 5)
        for process in processes:stop_owned_planner(process)
        executor.shutdown()
        if thread.ident:thread.join(timeout=5);assert not thread.is_alive()
        client.destroy()
        for node in (world, adapter, odom):node.destroy_node()
        rclpy.shutdown()
        for log in logs:log.close()
