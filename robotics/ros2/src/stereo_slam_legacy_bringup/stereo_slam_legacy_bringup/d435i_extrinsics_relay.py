"""不改图像和内参，为 OpenVINS 转发 IMU 并注入 Kalibr 双目基线."""

import math

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo
from sensor_msgs.msg import Imu


class D435iExtrinsicsRelay(Node):
    """为 D435i 的 IMU 和右目 CameraInfo 注入 Kalibr 外参."""

    def __init__(self):
        """声明外参参数，并创建 IMU 与右目 CameraInfo 转发通道."""
        super().__init__('d435i_extrinsics_relay')

        self.input_topic = self.declare_parameter(
            'input_topic', '/camera/camera/imu').value
        self.output_topic = self.declare_parameter(
            'output_topic', '/camera/camera/imu_kalibr').value
        self.output_frame_id = self.declare_parameter(
            'output_frame_id', 'd435i_kalibr_imu').value
        self.imu_time_offset_ms = float(self.declare_parameter(
            'imu_time_offset_ms', 0.0).value)
        self.right_info_input_topic = self.declare_parameter(
            'right_info_input_topic',
            '/camera/camera/infra2/camera_info',
        ).value
        self.right_info_output_topic = self.declare_parameter(
            'right_info_output_topic',
            '/camera/camera/infra2/camera_info_kalibr_extrinsics',
        ).value
        self.stereo_baseline = self.declare_parameter(
            'stereo_baseline', 0.04997166711450362).value

        # 输入、输出不能相同，否则本节点会收到自己发布的消息并形成循环。
        if self.input_topic == self.output_topic:
            raise ValueError('input_topic and output_topic must be different')
        if self.right_info_input_topic == self.right_info_output_topic:
            raise ValueError(
                'right info input and output topics must be different')
        if not self.output_frame_id:
            raise ValueError('output_frame_id must not be empty')
        if not math.isfinite(self.imu_time_offset_ms):
            raise ValueError('imu_time_offset_ms must be finite')
        if self.stereo_baseline <= 0.0:
            raise ValueError('stereo_baseline must be positive')

        self.publisher = self.create_publisher(
            Imu, self.output_topic, qos_profile_sensor_data)
        self.subscription = self.create_subscription(
            Imu,
            self.input_topic,
            self.relay_imu,
            qos_profile_sensor_data,
        )
        self.right_info_publisher = self.create_publisher(
            CameraInfo,
            self.right_info_output_topic,
            qos_profile_sensor_data,
        )
        self.right_info_subscription = self.create_subscription(
            CameraInfo,
            self.right_info_input_topic,
            self.relay_right_camera_info,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f'IMU frame relay: {self.input_topic} -> {self.output_topic}, '
            f'frame_id={self.output_frame_id}, '
            f'time_offset={self.imu_time_offset_ms:.6f} ms')
        self.get_logger().info(
            'Right CameraInfo extrinsics relay: '
            f'{self.right_info_input_topic} -> '
            f'{self.right_info_output_topic}, '
            f'baseline={self.stereo_baseline:.12f} m')

    def shift_imu_stamp(self, message):
        """按毫秒偏移 IMU 时间戳，使其与 Kalibr 的相机时间基准一致."""
        # 使用整数纳秒运算，避免浮点秒拆分造成进位误差。
        stamp_ns = (
            message.header.stamp.sec * 1_000_000_000
            + message.header.stamp.nanosec
        )
        shifted_ns = stamp_ns + round(self.imu_time_offset_ms * 1_000_000.0)
        if shifted_ns < 0:
            raise ValueError('shifted IMU timestamp must not be negative')
        message.header.stamp.sec = shifted_ns // 1_000_000_000
        message.header.stamp.nanosec = shifted_ns % 1_000_000_000

    def relay_imu(self, message):
        """保留测量值，修正时间戳并改写为 Kalibr 使用的 IMU frame_id."""
        self.shift_imu_stamp(message)
        message.header.frame_id = self.output_frame_id
        self.publisher.publish(message)

    def relay_right_camera_info(self, message):
        """仅按 Kalibr 基线更新右目 P[3]，其余内参和时间戳保持不变."""
        # 对已矫正双目，P[3] = -fx * baseline；这是相机间外参平移项。
        if message.p[0] <= 0.0:
            self.get_logger().error(
                'right CameraInfo P[0] must be positive, message dropped')
            return
        message.p[3] = -message.p[0] * self.stereo_baseline
        self.right_info_publisher.publish(message)


def main(args=None):
    """启动 D435i 外参转发节点并持续处理消息."""
    rclpy.init(args=args)
    node = D435iExtrinsicsRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        # ros2 launch 结束时会发送 SIGINT，按正常退出处理。
        pass
    finally:
        node.destroy_node()
        # Humble 的默认 SIGINT 处理器可能已经关闭 context，避免重复 shutdown。
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
