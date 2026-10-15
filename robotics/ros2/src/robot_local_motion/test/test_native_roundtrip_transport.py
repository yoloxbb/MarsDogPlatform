"""Exercise original C++ follow + MPPI, with no approach Action server or hardware."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import pytest

pytest.importorskip('rclpy')
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rcl_interfaces.srv import GetParameters
from std_msgs.msg import String
from robot_local_motion_runtime.native_roundtrip import NativeUwbRoundTrip
from test_roundtrip_transport import DualWorld, until
from test_task_transport import stop_owned_planner


@pytest.fixture(scope='module')
def native_stack(tmp_path_factory):
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1' and os.environ.get('ROS_DOMAIN_ID') == '226'
    from ament_index_python.packages import get_package_share_directory as share
    directory = tmp_path_factory.mktemp('native-roundtrip')
    own = Path(share('robot_local_motion'))
    old = Path(share('go2_uwb_local_follow'))
    processes, logs = [], []
    rclpy.init(args=['--ros-args', '--params-file', str(own/'config/lingmao_roundtrip.yaml'),
        '-p', 'enable_motion:=true', '-p', 'odom_topic:=/test/odom', '-p', 'odom_child_frame:=base_link'])
    world = DualWorld()
    demo = NativeUwbRoundTrip(parameter_overrides=[Parameter('owner_id', value='0x87654322'),
        Parameter('frisbee_id', value='0x87654324')])
    statuses = []
    world.create_subscription(String, '/uwb_roundtrip/status', lambda msg:
        statuses.append((time.monotonic(), json.loads(msg.data))), 10)
    configs = [('uwb_follow_controller_node', old/'config/uwb_follow_only.yaml', {
        'enable_motion': 'false', 'tracking_enabled': 'false', 'odom_topic': '/test/odom',
        'target_topic': '/uwb_roundtrip/selected_target', 'cmd_vel_topic': '/test/follow_debug',
        'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
        'diagnostics_topic': '/uwb_roundtrip/follow_diagnostics', 'min_linear_speed': '0.10'}),
      ('local_velocity_planner_node', old/'config/local_velocity_planner.yaml', {
        'enable_motion': 'true', 'odom_topic': '/test/odom', 'odom_child_frame': 'base_link',
        'obstacle_topic': '/test/cloud', 'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
        'final_cmd_topic': '/robot_local_motion/final_cmd', 'cmd_vel_topic': '/test/cmd_vel',
        'min_linear_speed': '0.10'})]
    try:
        for executable, config, params in configs:
            log = (directory/(executable+'.log')).open('w');logs.append(log)
            args = ['ros2', 'run', 'go2_uwb_local_follow', executable, '--ros-args',
                '--params-file', str(config), '--params-file', str(own/'config/lingmao_roundtrip.yaml')]
            for key, value in params.items():args += ['-p', key+':='+value]
            processes.append(subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        executor = MultiThreadedExecutor(num_threads=2)
        for node in (world, demo):executor.add_node(node)
        thread = threading.Thread(target=executor.spin);thread.start()
        until(lambda: demo.client.service_is_ready() and demo.stationary(time.monotonic())
            and demo.zero_output(time.monotonic()), 8)
        yield world, demo, statuses
    finally:
        if demo.phase not in ('IDLE', 'DONE', 'CANCELED'):
            demo.request_cancel()
            until(lambda: demo.phase == 'CANCELED', 8)
        for process in processes:stop_owned_planner(process)
        if 'executor' in locals():executor.shutdown()
        if 'thread' in locals():thread.join(timeout=5);assert not thread.is_alive()
        demo.destroy_node();world.destroy_node();rclpy.shutdown()
        for log in logs:log.close()


def reset(world, demo, distance=3.):
    world.fixed_obstacles = []
    world.owner_enabled = world.frisbee_enabled = True
    world.owner_x = world.x
    world.frisbee_x = world.x+distance
    world.yaw = 0.
    time.sleep(.7)
    assert demo.start_roundtrip()[0]


def cancel(demo):
    demo.request_cancel()
    until(lambda: demo.phase == 'CANCELED', 6)
    assert demo.stop_confirmed


def test_original_follow_node_switches_distance_and_completes_roundtrip(native_stack):
    world, demo, statuses = native_stack
    reset(world, demo)
    until(lambda: demo.phase == 'DWELL', 25)
    assert .68 <= abs(world.frisbee_x-world.x) <= .89
    dwell = demo.dwell_started
    until(lambda: demo.phase == 'DONE', 30)
    assert .85 <= abs(world.x-world.owner_x) <= 1.10
    return_states = [t for t,s in statuses if t>=dwell and s['state']=='RETURN_OWNER']
    assert return_states and return_states[0]-dwell >= 3.
    assert demo.outcome == 'SUCCEEDED' and demo.stop_confirmed
    assert [x['mode'] for x in demo.history] == ['original_uwb_follow', 'original_uwb_follow']
    assert not hasattr(demo, 'goal_handle')
    assert world.count_publishers('/test/cmd_vel') == 1


def test_near_target_holds_and_dwell_can_be_canceled(native_stack):
    world, demo, _ = native_stack
    reset(world, demo, .3)
    until(lambda: demo.phase == 'DWELL', 5)
    assert demo.outcome != 'NO_VALID_GOAL'
    cancel(demo)
    time.sleep(3.1)
    assert demo.phase == 'CANCELED' and len(demo.history)==1


def test_original_target_loss_pauses_and_recovers_without_task_failure(native_stack):
    world, demo, _ = native_stack
    reset(world, demo, 5.)
    until(lambda: world.v > .1, 5)
    world.frisbee_enabled = False
    until(lambda: abs(world.v)<1e-6 and abs(world.w)<1e-6, 3)
    time.sleep(3.2)
    assert demo.phase == 'APPROACH_FRISBEE' and not demo.outcome
    world.frisbee_enabled = True
    until(lambda: world.v>.1, 4)
    cancel(demo)


def test_original_emergency_reverse_waits_for_rear_clearance(native_stack):
    world, demo, _ = native_stack
    reset(world, demo, -4.)
    world.fixed_obstacles = [(world.x+.5,world.y),(world.x-.5,world.y)]
    time.sleep(1.)
    assert abs(world.v)<1e-6
    world.fixed_obstacles = [world.fixed_obstacles[0]]
    until(lambda: world.v<-.01, 4)
    cancel(demo)


def test_tracking_pause_and_distance_use_real_node_parameters(native_stack):
    world, demo, _ = native_stack
    client = world.create_client(GetParameters, '/uwb_follow_controller_node/get_parameters')
    assert client.wait_for_service(timeout_sec=3)
    future = client.call_async(GetParameters.Request(names=['tracking_enabled','follow_distance']))
    until(future.done, 3)
    values = future.result().values
    assert not values[0].bool_value
    assert values[1].double_value == demo.distances[demo.leg]
    world.destroy_client(client)
