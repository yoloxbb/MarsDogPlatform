"""Opt-in local task stack. Output is isolated unless explicitly redirected."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration as LC
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue as PV


def generate_launch_description():
    own = Path(get_package_share_directory('robot_local_motion'))
    old = Path(get_package_share_directory('go2_uwb_local_follow'))
    defaults = {
        'enable_motion': 'false', 'cmd_vel_topic': '/robot_local_motion/cmd_vel',
        'start_server': 'true', 'planner_cmd_vel_topic': '/robot_local_motion/planner_raw',
        'server_params_file': str(own / 'config/local_motion.yaml'),
        'chassis_params_file': LC('server_params_file'),
        'planner_params_file': str(old / 'config/local_velocity_planner.yaml'),
        'rolling_map_params_file': str(old / 'config/rolling_obstacle_map.yaml'),
        'odom_topic': '/leg_odom2', 'base_frame': 'base_footprint', 'odom_frame': 'odom',
        'odom_child_frame': LC('base_frame'),
        'action_name': '/robot_local_motion/execute',
        'observation_topic': '/local_depth_observation',
        'obstacle_topic': '/robot_local_motion/rolling_obstacle',
        'start_rolling_map': 'true', 'start_uwb_bridge': 'false',
        'start_uwb_multitag': 'false',
        'uwb_multitag_params_file': str(own / 'config/uwb_multitag.yaml'),
        'uwb_point_topic': '/uwb/target_point', 'uwb_target_id': 'owner',
        'start_obstacle_projection': 'false', 'start_uwb_adapter': 'false',
        'projection_params_file': str(old / 'config/stereo_obstacle_cloud.yaml'),
        'uwb_adapter_params_file': str(old / 'config/uwb_follow_only.yaml'),
        'uwb_raw_topic': '/libAoa_robot_publisher',
        'left_image': '/camera/camera/infra1/image_rect_raw',
        'right_image': '/camera/camera/infra2/image_rect_raw',
        'left_camera_info': '/camera/camera/infra1/camera_info',
        'right_camera_info': '/camera/camera/infra2/camera_info',
    }
    frames = {'base_frame': LC('base_frame'), 'odom_frame': LC('odom_frame'),
              'odom_child_frame': LC('odom_child_frame'), 'odom_topic': LC('odom_topic')}
    planner = Node(package='go2_uwb_local_follow', executable='local_velocity_planner_node',
        name='local_velocity_planner_node', output='screen',
        parameters=[LC('planner_params_file'), LC('server_params_file'), LC('chassis_params_file'), frames, {
            'enable_motion': PV(LC('enable_motion'), value_type=bool),
            'enable_task_parameters': True,
            'obstacle_topic': LC('obstacle_topic'),
            'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
            'planned_cmd_topic': '/robot_local_motion/planned_cmd',
            'final_cmd_topic': '/robot_local_motion/final_cmd',
            'cmd_vel_topic': LC('planner_cmd_vel_topic'),
            'diagnostics_topic': '/robot_local_motion/planner_diagnostics',
            'selected_path_topic': '/robot_local_motion/selected_path'}])
    server = Node(package='robot_local_motion', executable='local_motion_server',
        name='local_motion_server', output='screen',
        condition=IfCondition(LC('start_server')),
        parameters=[LC('server_params_file'), LC('chassis_params_file'), frames, {
            'enable_motion': PV(LC('enable_motion'), value_type=bool),
            'action_name': LC('action_name'),
            'cmd_vel_topic': LC('cmd_vel_topic'), 'obstacle_topic': LC('obstacle_topic')}])
    rolling = Node(package='go2_uwb_local_follow', executable='rolling_obstacle_map_node',
        name='rolling_obstacle_map_node', condition=IfCondition(LC('start_rolling_map')),
        parameters=[LC('rolling_map_params_file'), frames, {
            'input_observation_topic': LC('observation_topic'),
            'output_obstacle_topic': LC('obstacle_topic')}])
    bridge = Node(package='robot_local_motion', executable='uwb_observation_bridge',
        name='uwb_observation_bridge', condition=IfCondition(LC('start_uwb_bridge')),
        parameters=[{'input_topic': LC('uwb_point_topic'), 'target_id': LC('uwb_target_id')}])
    uwb_adapter = Node(package='go2_uwb_local_follow', executable='uwb_target_adapter_node',
        name='uwb_target_adapter_node', condition=IfCondition(LC('start_uwb_adapter')),
        parameters=[LC('uwb_adapter_params_file'), {'target_frame': LC('base_frame'),
            'raw_topic': LC('uwb_raw_topic'), 'target_topic': LC('uwb_point_topic')}])
    multitag = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(own / 'launch/uwb_multitag.launch.py')),
        condition=IfCondition(LC('start_uwb_multitag')),
        launch_arguments={'enable_serial': 'true', 'params_file': LC('uwb_multitag_params_file')}.items())
    projection = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(old / 'launch/stereo_obstacle_cloud.launch.py')),
        condition=IfCondition(LC('start_obstacle_projection')),
        launch_arguments={
            'params_file': LC('projection_params_file'), 'base_frame': LC('base_frame'),
            'left_image': LC('left_image'), 'right_image': LC('right_image'),
            'left_camera_info': LC('left_camera_info'), 'right_camera_info': LC('right_camera_info'),
            'ray_observation_topic': LC('observation_topic'),
            'disparity_topic': '/robot_local_motion/disparity',
            'obstacle_cloud_topic': '/robot_local_motion/instant_obstacle',
            'compute_enable_topic': '/robot_local_motion/perception_enable', 'start_enabled': 'true',
        }.items())
    return LaunchDescription([*[DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()],
                              projection, rolling, uwb_adapter, multitag, planner, server, bridge])
