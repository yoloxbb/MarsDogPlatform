# D435i 接入 VINS-Fusion ROS2 运行记录

本文档记录在本机把 Intel RealSense D435i 接入 VINS-Fusion ROS2 Humble 的步骤。
目标输入是双目红外图像加合成 IMU，不使用深度图、点云和 RGB 图像。

执行本文命令前先运行 `source ~/robot_ws/scripts/setup_robot_env.sh`；仓库不在默认位置时，直接 source 实际克隆目录中的同名脚本。

## 1. 当前配置

VINS 配置文件：

```bash
config/realsense_d435i/realsense_stereo_imu_config.yaml
```

当前使用的话题：

```text
/camera/camera/infra1/image_rect_raw
/camera/camera/infra2/image_rect_raw
/camera/camera/imu
```

相机配置：

```text
config/realsense_d435i/left.yaml
config/realsense_d435i/right.yaml
```

已按本机 D435i 的 `/camera/camera/infra1/camera_info` 和
`/camera/camera/infra2/camera_info` 更新为 `640x480` 红外 rectified 内参：

```text
fx = 389.9342346191406
fy = 389.9342346191406
cx = 321.290771484375
cy = 239.03565979003906
```

`body_T_cam0` 和 `body_T_cam1` 先作为初值使用，配置中保留：

```yaml
estimate_extrinsic: 1
estimate_td: 1
```

当前 `body_T_cam0/body_T_cam1` 已按本机 `/tf_static` 中
`camera_imu_optical_frame -> camera_infra1/2_optical_frame` 更新：

```text
body_T_cam0 t = [-0.00552, 0.00510, 0.01174], R = I
body_T_cam1 t = [ 0.0445195522, 0.00510, 0.01174], R = I
```

长期稳定运行建议用 Kalibr 或 RealSense factory extrinsics 重新标定后，再改成
`estimate_extrinsic: 0`。

## 2. RealSense 驱动

本机已安装：

```bash
sudo apt install ros-humble-realsense2-camera
```

如果启动时报：

```text
libdiagnostic_updater.so: cannot open shared object file
```

升级：

```bash
sudo apt install ros-humble-diagnostic-updater
```

D435i IMU 容易被 `iio-sensor-proxy` 占用，本机已停用并 mask：

```bash
sudo systemctl stop iio-sensor-proxy
sudo systemctl disable iio-sensor-proxy
sudo systemctl mask iio-sensor-proxy
```

本机还增加了持久 IIO 权限修复：

```text
/etc/udev/rules.d/99-realsense-d435i-iio.rules
/usr/local/sbin/fix-realsense-iio-perms.sh
```

原因是 D435i 重置或重插后，`/sys/bus/iio/devices/iio:device*/buffer`
和 `trigger/current_trigger` 会恢复为 root 只写，导致 RealSense 打不开 IMU。

确认设备：

```bash
source /opt/ros/humble/setup.bash
rs-enumerate-devices
```

应能看到：

```text
Intel RealSense D435I
Usb Type Descriptor: 3.2
Imu Type: BMI085
```

## 3. 启动 D435i

只开启 VINS 需要的红外双目和 IMU：

```bash
source /opt/ros/humble/setup.bash
ros2 launch realsense2_camera rs_launch.py \
  initial_reset:=true \
  enable_color:=false \
  enable_depth:=false \
  enable_infra1:=true \
  enable_infra2:=true \
  enable_gyro:=true \
  enable_accel:=true \
  unite_imu_method:=2 \
  enable_sync:=true \
  depth_module.infra_profile:=640x480x30 \
  gyro_fps:=200 \
  accel_fps:=200
```

另开终端检查：

```bash
source /opt/ros/humble/setup.bash
ros2 topic list | grep camera
ros2 topic hz /camera/camera/infra1/image_rect_raw
ros2 topic hz /camera/camera/infra2/image_rect_raw
ros2 topic hz /camera/camera/imu
ros2 topic echo /camera/camera/imu --once
```

如果 `/camera/camera/imu` 只有话题但没有消息，先执行：

```bash
sudo systemctl stop iio-sensor-proxy
sudo systemctl mask iio-sensor-proxy
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo /usr/local/sbin/fix-realsense-iio-perms.sh
```

再重新启动 RealSense 节点。失败日志形态通常是：

```text
iio_hid_sensor: Frames didn't arrived within the predefined interval
```

## 4. 录制测试 bag

建议先录 30-60 秒，方便复现问题：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
mkdir -p datasets/d435i

ros2 bag record \
  /camera/camera/infra1/image_rect_raw \
  /camera/camera/infra2/image_rect_raw \
  /camera/camera/imu \
  -o datasets/d435i/d435i_stereo_imu_test
```

录制时手持相机做左右、前后、上下平移，不要只原地转动。

## 5. 运行 VINS

终端 1，启动 RViz 和 D435i TF 桥接：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vins d435i_vins_rviz.launch.xml
```

终端 2，启动 VINS：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run vins vins_node config/realsense_d435i/realsense_stereo_imu_config.yaml
```

终端 3，播放 bag：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
ros2 bag play datasets/d435i/d435i_stereo_imu_test
```

## 6. 排错重点

- 一直 `wait for imu`：先检查 `/camera/camera/imu` 是否真的有消息。
- 提示 QoS 不匹配：确认 VINS 已重新编译，`vins/src/rosNodeTest.cpp` 里的 IMU 和图像订阅应使用 `best_effort`。
- 没有图像：检查 RealSense 话题是否和配置文件一致。
- TF 树分成 `world -> body -> camera` 和 `camera_link -> ...` 两棵：D435i 运行时使用 `ros2 launch vins d435i_vins_rviz.launch.xml`，其中会发布 `body -> camera_link` 静态桥接。
- 初始化慢：增加平移运动，避免纯旋转和低纹理场景。
- 轨迹快速飞掉：优先检查左右图像是否反了、相机内参是否和 camera_info 一致、外参方向是否正确。
- 虚拟机中不稳定：确认 D435i 是 USB 3.0/3.2 直通，不要走 USB 2.0。

## 7. 接入 RTAB-Map

RTAB-Map 使用 VINS 输出作为外部里程计时，订阅关系应为：

```text
stereo images: /camera/camera/infra1/image_rect_raw
               /camera/camera/infra2/image_rect_raw
camera_info:   /camera/camera/infra1/camera_info
               /camera/camera/infra2/camera_info
odom:          /odometry
base frame:    body
odom frame:    world
```

`${ROBOT_WS_ROOT}/slam_ws/src/stereo_slam_legacy_bringup/launch/d435i_openvins_rtabmap.launch.py`
中 RTAB-Map 的关键参数建议改为：

```python
'frame_id': 'body',
'subscribe_stereo': True,
'subscribe_odom_info': False,
'approx_sync': True,
'approx_sync_max_interval': 0.1,
'wait_for_transform': 0.5,
'Rtabmap/ImagesAlreadyRectified': 'true',
'Reg/Force3DoF': 'false',
```

关键 remap：

```python
('left/image_rect', '/camera/camera/infra1/image_rect_raw'),
('right/image_rect', '/camera/camera/infra2/image_rect_raw'),
('left/camera_info', '/camera/camera/infra1/camera_info'),
('right/camera_info', '/camera/camera/infra2/camera_info'),
('odom', '/odometry'),
```

如果设备固定在平面小车上，再按需要把 `Reg/Force3DoF` 改回 `true`。

## 8. 本次实测状态

- D435i 已识别：`Intel RealSense D435I`，USB `3.2`，IMU `BMI085`。
- `ros-humble-realsense2-camera` 已安装，`diagnostic_updater` 已升级到带 `libdiagnostic_updater.so` 的版本。
- 必须用 `depth_module.infra_profile:=640x480x30` 启动；`infra_width/infra_height/infra_fps` 会被当前 RealSense ROS2 驱动忽略，导致实际输出变成 `848x480`。
- `/camera/camera/infra1/image_rect_raw` 和 `/camera/camera/infra2/image_rect_raw` 已验证约 `30Hz`。
- `/camera/camera/infra1/camera_info` 和 `/camera/camera/infra2/camera_info` 已能读取，`640x480` 内参已同步到 `left.yaml` / `right.yaml`。
- `/camera/camera/imu` 已验证约 `199.6Hz`，`ros2 topic echo /camera/camera/imu --once` 能拿到角速度和加速度。
- 已验证 `initial_reset:=true` 后 IIO 权限仍会自动恢复，RealSense IMU 能正常启动。
- VINS 传感器输入 QoS 已改为 `best_effort`，并已短测确认没有 QoS incompatibility 警告。
- VINS `/odometry` 已调整为 `header.frame_id=world`、`child_frame_id=body`，可作为 RTAB-Map 外部 odometry 输入。
- 在线冻结发布外参方案已撤销；当前不再发布 `/vins/extrinsic/*` 和 `/calibration/*`，RTAB-Map 继续只使用 `/odometry` 作为外部里程计输入。
