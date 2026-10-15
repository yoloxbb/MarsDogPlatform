"""One scenario per launch; retain original follow, roundtrip and circle control."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration as LC
from launch_ros.actions import Node
from robot_local_motion_runtime.native_follow_launch import native_stack


def setup(context):
    keys = DEFAULTS
    v = {key: LC(key).perform(context) for key in keys}
    scenario = v['scenario']
    own = Path(get_package_share_directory('robot_local_motion'))
    if scenario == 'frisbee':
        args = {k: v[k] for k in ('owner_id', 'frisbee_id', 'enable_motion', 'enable_serial',
            'autostart', 'chassis_params_file', 'odom_topic', 'odom_child_frame',
            'cmd_vel_topic', 'start_obstacle_projection')}
        return [IncludeLaunchDescription(PythonLaunchDescriptionSource(str(own/'launch/uwb_roundtrip.launch.py')),
                                         launch_arguments=args.items())]
    if scenario not in ('follow', 'point', 'vision', 'play'):
        raise ValueError('scenario must be follow, frisbee, point, vision or play')
    play = scenario == 'play'
    distance = float(v['follow_distance'] or ('0.0' if scenario == 'point' else '0.8' if scenario == 'vision' else '1.0'))
    nodes, minimum, decel = native_stack(v, '/target_follow/selected_target',
        '/target_follow/follow_diagnostics', distance=distance,
        with_follow=not play, planner_output='/target_follow/play_planner_cmd' if play else None)
    kind = ('vision' if scenario == 'vision' else
            ('point' if scenario == 'point' else 'uwb') if v['target_input'] == 'auto' else v['target_input'])
    if kind not in ('point', 'uwb') and scenario != 'vision':
        raise ValueError('target_input must be uwb or point')
    if play and kind != 'uwb':
        raise ValueError('play uses the existing UWB circle behavior')
    if kind == 'uwb':
        nodes.append(Node(package='robot_local_motion', executable='uwb_multitag_input',
            name='uwb_multitag_input', parameters=[str(own/'config/uwb_multitag.yaml'),
                {'enable_serial': v['enable_serial'].lower() == 'true'}]))
    nodes.append(Node(package='robot_local_motion', executable='target_follow_input',
        name='target_follow_input', output='screen', parameters=[{
            'input_mode': 'fixed' if scenario in ('point', 'vision') else 'stream',
            'input_kind': kind, 'target_id': v['target_id'],
            'autostart': True if play else v['autostart'].lower() == 'true', 'manage_tracking': not play,
            'odom_topic': v['odom_topic'], 'point_topic': v['point_topic'],
            'vision_topic': v['vision_topic'], 'vision_label': v['vision_label'],
            'vision_target_id': v['vision_target_id'], 'depth_topic': v['depth_topic'],
            'camera_info_topic': v['camera_info_topic']}]))
    if play:
        behavior = Path(get_package_share_directory('go2_uwb_behavior'))
        nodes.append(Node(package='robot_local_motion', executable='behavior_odom_input',
            parameters=[{'odom_topic': v['odom_topic']}]))
        nodes.append(Node(package='go2_uwb_behavior', executable='uwb_behavior_controller_node',
            name='uwb_behavior_controller_node', output='screen', parameters=[
                str(behavior/'config/behavior_controller.yaml'),
                {'target_topic': '/target_follow/selected_target', 'odom_topic': '/target_follow/behavior_odom',
                 'hardware_id': 'lingmao', 'enable_motion': v['enable_motion'].lower() == 'true',
                 'obstacle_topic': '/robot_local_motion/rolling_obstacle',
                 'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
                 'planner_cmd_topic': '/target_follow/play_planner_cmd',
                 'planner_diagnostics_topic': '/robot_local_motion/planner_diagnostics',
                 'cmd_vel_topic': v['cmd_vel_topic'],
                 'compute_enable_topic': '/robot_local_motion/perception_enable',
                 'min_linear_speed': minimum, 'max_linear_decel': decel,
                 'max_linear_speed': 1., 'max_angular_speed': 1.2, 'blind_rotation_max_speed': 1.2},
                *([str(Path(v['play_params_file']).expanduser())] if v['play_params_file'] else [])]))
    return nodes


DEFAULTS = dict(scenario='follow', target_input='auto', target_id='0x87654322',
    follow_distance='', owner_id='0x87654322', frisbee_id='0x87654324',
    enable_motion='false', enable_serial='false', autostart='false', chassis_params_file='',
    odom_topic='/odom', odom_child_frame='base_link', cmd_vel_topic='/robot_local_motion/cmd_vel',
    start_obstacle_projection='true', point_topic='/target_follow/point',
    vision_topic='/perception/vision/object_detections', vision_label='', vision_target_id='',
    depth_topic='/camera/camera/aligned_depth_to_color/image_raw',
    camera_info_topic='/camera/camera/color/camera_info', play_params_file='')


def generate_launch_description():
    return LaunchDescription([*[DeclareLaunchArgument(k, default_value=v) for k, v in DEFAULTS.items()],
                              OpaqueFunction(function=setup)])
