# robot_slam_bringup

GO2 D435i 与 HB USB 双目的常用 OpenVINS、RTAB-Map、Nav2 启动包。

本包是当前推荐的建图导航入口。传感器驱动统一由 `sensor_ws` 提供，
本包只负责组合传感器、OpenVINS、RTAB-Map 和 Nav2。

## 文件说明

- `go2_d435i_slam_nav2.launch.py`：GO2 + D435i 建图、重定位和可选 Nav2。
- `hb_stereo_slam.launch.py`：HB USB 双目 + WIT IMU 建图。
- `openvins_rtabmap.launch.py`：两套入口共用的 OpenVINS/RTAB-Map 管线。
- `openvins_rtabmap.yaml`：OpenVINS 与 RTAB-Map 参数。
- `go2_nav2.yaml`：GO2 Nav2 参数。
- `hb_left_camera.yaml`、`hb_right_camera.yaml`：HB 双目标定参数。
- `d435i_extrinsics_relay.py`：转发 D435i IMU frame，并更新右目双目基线。

## 构建

```bash
source "$(git rev-parse --show-toplevel)/scripts/setup_robot_env.sh"
source /opt/ros/humble/setup.bash
cd "${ROBOT_WS_ROOT}/sensor_ws"
colcon build --symlink-install --executor sequential
source install/setup.bash

cd "${ROBOT_WS_ROOT}/slam_ws"
colcon build --packages-select robot_slam_bringup --symlink-install
source install/setup.bash
```

## 常用启动方式

GO2 建图：

```bash
ros2 launch robot_slam_bringup go2_d435i_slam_nav2.launch.py \
  localization:=false \
  navigation:=false \
  delete_db_on_start:=true \
  database_path:=$HOME/.ros/rtabmap_go2_d435i.db
```

GO2 使用已有数据库重定位并启动 Nav2：

```bash
ros2 launch robot_slam_bringup go2_d435i_slam_nav2.launch.py \
  localization:=true \
  navigation:=true \
  delete_db_on_start:=false \
  database_path:=$HOME/.ros/rtabmap_go2_d435i.db
```

HB 双目建图：

```bash
ros2 launch robot_slam_bringup hb_stereo_slam.launch.py
```

GO2 入口不会启动 D435i 驱动；启动本包前应先启动 RealSense，并确认合并后的
IMU 话题、双目图像和 TF 已正常发布。
