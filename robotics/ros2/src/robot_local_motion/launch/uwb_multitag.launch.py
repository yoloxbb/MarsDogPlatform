"""Only the UWB input node; no chassis, local task server or planner is started."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration as LC
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    defaults = {
        'enable_serial': 'false',
        'params_file': str(Path(get_package_share_directory('robot_local_motion')) / 'config/uwb_multitag.yaml'),
        'port': '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AG00S82A-if00-port0',
    }
    return LaunchDescription([
        *[DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()],
        Node(package='robot_local_motion', executable='uwb_multitag_input', name='uwb_multitag_input',
             output='screen', parameters=[LC('params_file'), {'port': LC('port'),
             'enable_serial': ParameterValue(LC('enable_serial'), value_type=bool)}])])
