#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维特(WIT)IMU -> ROS2 sensor_msgs/Imu 发布节点

数据流:
  串口原始字节 -> 按 0x55 帧头拆 11 字节帧 -> 校验 -> 按类型解析
  -> 攒齐 加速度(0x51)/角速度(0x52)/角度(0x53) -> 组装 Imu 消息 -> 发布

单位换算(ROS 里 Imu 消息要求的是国际单位):
  加速度: g   -> m/s^2   要 × 9.80665
  角速度: °/s -> rad/s   要 × π/180
  角度  : °   -> rad,再由 Roll/Pitch/Yaw 转成四元数(orientation)
"""
import math
import struct

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import serial
from sensor_msgs.msg import Imu

G = 9.80665                 # 1g 对应的重力加速度 m/s^2
DEG2RAD = math.pi / 180.0   # 角度转弧度


def s16(lo, hi):
    """两个字节(小端,低字节在前)拼成有符号16位整数"""
    return struct.unpack("<h", bytes([lo, hi]))[0]


def euler_to_quat(roll, pitch, yaw):
    """
    欧拉角(弧度)->四元数。维特输出的是 ZYX 顺序(先绕Z偏航,再Y,再X)。
    公式里 cy/sy 是 yaw 的半角余弦/正弦,cp/sp 是 pitch,cr/sr 是 roll。
    返回 (x, y, z, w)。
    """
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    w = cr * cp * cy + sr * sp * sy
    return x, y, z, w


class WitImuNode(Node):
    def __init__(self):
        super().__init__("wit_imu_node")

        # ---- 可在 launch / 命令行覆盖的参数 ----
        self.declare_parameter("port", "/dev/ttyUSB0")
        self.declare_parameter("baud", 115200)
        self.declare_parameter("frame_id", "imu_link")
        self.declare_parameter("topic", "imu/data_raw")

        port = self.get_parameter("port").value
        baud = self.get_parameter("baud").value
        self.frame_id = self.get_parameter("frame_id").value
        topic = self.get_parameter("topic").value

        # 传感器数据用 BEST_EFFORT 更合适(丢一帧无所谓,别阻塞)
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.pub = self.create_publisher(Imu, topic, qos)

        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
        except Exception as e:
            self.get_logger().error(f"打开串口 {port}@{baud} 失败: {e}")
            raise
        self.get_logger().info(f"已打开 {port}@{baud},发布话题: {topic},frame_id={self.frame_id}")

        self.buf = bytearray()
        # 最新的加速度/角速度/角度,攒齐后一起发
        self.acc = [0.0, 0.0, 0.0]      # m/s^2
        self.gyro = [0.0, 0.0, 0.0]     # rad/s
        self.quat = [0.0, 0.0, 0.0, 1.0]  # x,y,z,w
        self.got_angle = False

        # 用定时器周期性读串口(比 while 循环更符合 ROS2 风格)
        self.timer = self.create_timer(0.005, self.poll)  # 200Hz 轮询

    def poll(self):
        """读一批字节,按帧解析,攒齐后发布"""
        n = self.ser.in_waiting            # 缓冲区里现有多少字节
        data = self.ser.read(n if n else 1)  # 全读走,避免200Hz下积压延迟
        if data:
            self.buf += data
        while len(self.buf) >= 11:
            if self.buf[0] != 0x55:
                self.buf.pop(0)          # 不是帧头,滑一格重新对齐
                continue
            frame = bytes(self.buf[:11])
            if (sum(frame[0:10]) & 0xFF) != frame[10]:
                self.buf.pop(0)          # 校验失败,丢一字节再找
                continue
            self.handle_frame(frame)
            del self.buf[:11]

    def handle_frame(self, f):
        t = f[1]
        x, y, z = s16(f[2], f[3]), s16(f[4], f[5]), s16(f[6], f[7])
        if t == 0x51:                    # 加速度: /32768*16 (g) -> *G
            k = 16.0 / 32768 * G
            self.acc = [x * k, y * k, z * k]
        elif t == 0x52:                  # 角速度: /32768*2000 (°/s) -> *DEG2RAD
            k = 2000.0 / 32768 * DEG2RAD
            self.gyro = [x * k, y * k, z * k]
        elif t == 0x53:                  # 角度: /32768*180 (°) -> 转四元数
            k = 180.0 / 32768 * DEG2RAD  # 直接得到弧度
            roll, pitch, yaw = x * k, y * k, z * k
            self.quat = list(euler_to_quat(roll, pitch, yaw))
            self.got_angle = True
            self.publish()               # 角度帧是一组数据的最后一帧,收到就发

    def publish(self):
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id

        msg.orientation.x = self.quat[0]
        msg.orientation.y = self.quat[1]
        msg.orientation.z = self.quat[2]
        msg.orientation.w = self.quat[3]

        msg.angular_velocity.x = self.gyro[0]
        msg.angular_velocity.y = self.gyro[1]
        msg.angular_velocity.z = self.gyro[2]

        msg.linear_acceleration.x = self.acc[0]
        msg.linear_acceleration.y = self.acc[1]
        msg.linear_acceleration.z = self.acc[2]

        # 协方差: 首元素置 -1 表示"该项无有效协方差估计"是惯例;
        # 这里给一个小的对角值,VIO/滤波器能用。可按实际噪声调。
        msg.orientation_covariance = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]
        msg.angular_velocity_covariance = [0.001, 0.0, 0.0, 0.0, 0.001, 0.0, 0.0, 0.0, 0.001]
        msg.linear_acceleration_covariance = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]

        self.pub.publish(msg)


def main():
    rclpy.init()
    node = WitImuNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
