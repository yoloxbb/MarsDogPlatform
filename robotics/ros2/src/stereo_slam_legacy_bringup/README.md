# stereo_slam_legacy_bringup 兼容建图入口

本包保留三套既有 launch，便于旧部署继续使用。新的 Lite3/D435i 外部里程计链路优先阅读 [robot_slam_bringup](../robot_slam_bringup/README.md)；兼容入口的传感器、标定和 TF 与主入口并不完全相同。

| 文件 | 功能与依赖 |
| --- | --- |
| `launch/ekf_rtabmap.launch.py` | 双目 VO `/vo` + 外部 `/odom` → `robot_localization` EKF `/odometry/filtered` → RTAB-Map；包含图像校正和固定安装 TF |
| `launch/d435i_openvins_rtabmap.launch.py` | D435i OpenVINS 兼容入口，默认 IMU `/camera/camera/imu`；可选足式速度输入 `/odom_leg`，默认关闭 |
| `launch/rtabmap_openvins_stereo_mapping.launch.py` | 上述 OpenVINS 入口使用的公共管线；单独运行时默认 WIT `/imu/data_raw` 和 `camera_info_kalibr`，需核对配置 |
| `config/ekf_stereo_wheel.yaml` | 2D EKF：`/odom` 速度、`/vo` 平面位姿，发布 odom TF |

按 [公共构建说明](../../README.md) 选择本包，并准备 RTAB-Map、image_proc、robot_localization 等依赖。它不启动物理相机和底盘驱动。

EKF 入口示例：

```bash
ros2 launch stereo_slam_legacy_bringup ekf_rtabmap.launch.py use_viz:=false
```

该入口输入为 `/stereo/left/camera/image_mono`、`/stereo/right/camera/image_mono` 及对应内参，不是主 D435i 入口的话题名。固定左右基线与 base→camera 安装 TF 是既有部署参数，换硬件需重新核对。RTAB-Map 明确订阅 EKF 输出 `/odometry/filtered`；启动参数固定带 `-d`，会重置默认数据库，没有数据库保留开关。

D435i 兼容入口默认 `delete_db_on_start=true`；保留旧数据库时显式设置 false。该入口虽然使用内置 IMU 话题，也必须核对它实际加载的 OpenVINS 标定，不能只凭文件名判断已适配当前设备。

文件保留是为了兼容入口和数据链路，不以“本地未提交修改”等临时 Git 状态作为使用依据。本次文档核对未重新验证兼容入口的硬件运行。
