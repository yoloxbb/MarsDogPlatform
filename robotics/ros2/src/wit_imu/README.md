# wit_imu WIT 串口 IMU

默认使用 C++ `wit_imu_node` 读取 WIT 0x55 串口帧，校验并组合加速度、角速度为 `sensor_msgs/Imu`。提供时间戳估计、断线重连和可选二阶低通滤波。Python 兼容节点由 CMake 安装为 `wit_imu_node_py`，不由默认 launch 启动。

## 数据含义

- 原始话题 `/imu/data_raw`：加速度单位 m/s²，角速度单位 rad/s。
- 滤波话题 `/imu/data_filtered`：对加速度和角速度低通；默认开启，截止频率 20 Hz。
- frame 默认 `imu_link`；本包不发布安装 TF。
- **不输出有效姿态估计**，`orientation_covariance[0]=-1`。它不是 Madgwick/互补滤波姿态融合器，也不会把设备角度帧当成已融合姿态。
- `expected_rate_hz` 用于采样周期和时间戳估计，不会把硬件输出频率自动设置成该值；设备实际波特率和频率需预先配置匹配。

## 启动参数

| 参数 | 默认值 |
| --- | --- |
| `port` | `/dev/ttyUSB0` |
| `baud` | 115200 |
| `expected_rate_hz` | 200.0 |
| `enable_low_pass` | true |
| `low_pass_cutoff_hz` | 20.0 |
| `raw_topic` | `/imu/data_raw` |
| `filtered_topic` | `/imu/data_filtered` |

按 [公共构建说明](../../README.md) 选择 `wit_imu`。加载安装环境后：

```bash
ros2 launch wit_imu wit_imu.launch.py port:=/dev/ttyUSB0 baud:=115200
```

若直接运行节点，可用 ROS 参数覆盖 frame 等节点参数：

```bash
ros2 run wit_imu wit_imu_node --ros-args -p frame_id:=imu_link
```

使用前确认串口权限和设备独占；GO2/OpenVINS 入口还需要与实际安装一致的相机—IMU 外参和时间同步。不能用 D435i 自带 IMU 替换 WIT 后继续沿用原安装标定。
