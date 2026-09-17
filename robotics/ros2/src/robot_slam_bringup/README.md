# robot_slam_bringup

GO2、D435i 的 RTAB-Map、OpenVINS、VINS-Fusion 与 Nav2 启动包。

`nav.launch.py` 是主要入口，相关导航配置和行为树均保留在本包中。
传感器驱动统一由 `sensor_ws` 提供，本包只负责组合里程计、建图和导航。

## 文件说明

- `nav.launch.py`：主要入口；CAPO 里程计 + D435i 双目 + RTAB-Map + 可选 Nav2。
- `go2_d435i_slam_nav2.launch.py`：保留的一套 GO2 OpenVINS 建图与导航入口。
- `openvins_rtabmap.launch.py`：上述入口使用的 OpenVINS/RTAB-Map 公共管线。
- `d435i_wit_vins_rtabmap.launch.py`：保留的一套 VINS-Fusion 视觉惯性入口。
- `openvins_rtabmap.yaml`：OpenVINS 与 RTAB-Map 参数。
- `go2_nav2.yaml`：GO2 Nav2 参数。
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

## 主要启动方式

CAPO 里程计 + RTAB-Map 建图：

```bash
ros2 launch robot_slam_bringup nav.launch.py
```

启动 Nav2：

```bash
ros2 launch robot_slam_bringup nav.launch.py use_nav2:=true
```

只使用双目视觉里程计时，应同时把 RTAB-Map 的里程计输入切到 `/vo`：

```bash
ros2 launch robot_slam_bringup nav.launch.py \
  use_stereo_odometry:=true \
  odom_topic:=/vo
```

## 其他保留入口

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

GO2 入口不会启动 D435i 驱动；启动本包前应先启动 RealSense，并确认合并后的
IMU 话题、双目图像和 TF 已正常发布。
