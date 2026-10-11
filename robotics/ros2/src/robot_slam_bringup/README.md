# robot_slam_bringup 建图与导航入口

核对日期：2026-10-12。本包是 Python launch/配置组合包，主要入口 `nav.launch.py` 通过 `robot:=lite3|go2|lingmao` 选择 Lite3、GO2 或宇泛灵猫配置，使用外部里程计和 D435i 双目启动 RTAB-Map，并可启动公共 MPPI/STVL 导航；另外保留历史 GO2/OpenVINS 和 VINS-Fusion 入口。

## 文件与算法

| 文件 | 功能与默认输入 |
| --- | --- |
| `launch/nav.launch.py` | 按机器人选择外部里程计 + D435i 校正双目 → RTAB-Map；可选双目 VO、公共 Nav2、可视化、URDF 和 keepout |
| `launch/go2_d435i_slam_nav2.launch.py` | GO2 frame 配置 + OpenVINS/RTAB-Map；可选定位和 Nav2 |
| `launch/openvins_rtabmap.launch.py` | RTAB-Map `stereo_odometry` 使用 `Odom/Strategy=10` 的 OpenVINS 后端，再接 RTAB-Map SLAM；不是单独启动 `ov_msckf` |
| `launch/d435i_wit_vins_rtabmap.launch.py` | 外部 `vins` 视觉惯性里程计 + RTAB-Map；`start_sensors=true` 时启动 RealSense/WIT |
| `config/nav.yaml` | 公共 Nav2（未覆盖时为原 Lite3 默认值）：Smac Hybrid + Constrained Smoother + Nav2 MPPI + STVL + 自由空间脱困 |
| `config/openvins_rtabmap.yaml` | OpenVINS 后端及 RTAB-Map 参数 |
| `config/go2_nav2.yaml` | 历史 GO2 DWB 配置；新三机器人入口均使用公共 nav.yaml |
| `config/robots/*.yaml` | 三套机器人专属接口、轮廓、速度、安装外参占位和来源记录 |
| `robot_slam_bringup/odometry_tf_relay.py` | 可选 Odometry → TF；灵猫官方桥仅发布消息时使用 |
| `config/navigate_to_pose_no_backup.xml` | 单点导航：目标变化或恢复后重规划；实际包含 `BackUp` 恢复 |
| `config/navigate_through_poses_no_backup.xml` | 多点导航行为树，恢复行为以内容为准 |
| `robot_slam_bringup/d435i_extrinsics_relay.py` | IMU frame 转发和右目基线 CameraInfo 修正辅助节点；仅由引用它的入口使用 |

当前主要入口和公共 OpenVINS 配置使用传统特征 `Kp/DetectorStrategy=8`、g2o `Optimizer/Strategy=1`。编译打开 GTSAM、LibTorch/SuperPoint 不会自动切换这些参数；SLAM 特征和图优化默认值保持原设置；新增 GO2/灵猫 profile 的导航使用公共 MPPI/STVL。

## 构建与前提

按 [公共构建说明](../../README.md) 准备依赖、选择 `robot_slam_bringup` 并加载安装环境。本板当前完整产物可直接加载 `out/rk3588-navigation/use-navigation.sh`，其中包含 RTAB-Map/OpenVINS、Nav2、STVL 和本启动包；详见 [导航构建与使用](../../NAVIGATION_BUILD.md)。VINS-Fusion 本次跳过。

主要 `nav.launch.py` **不启动 RealSense、WIT 或底盘驱动**。先由部署层提供图像、CameraInfo、底盘里程计与完整 TF。该文件直接导入 Nav2 launch 工具并查找 `nav2_bringup`，因此即使 `use_nav2=false`，解析 launch 也需要相应 Nav2 包。完整 `nav.yaml` 还需要 MPPI、Smac、Constrained Smoother、STVL、DenoiseLayer 和本仓库 `behavior_ext_plugins`；插件兼容性按实际 Nav2 版本核对。

## 主要入口默认参数（未指定 robot 时为 Lite3）

| 参数 | 默认值 |
| --- | --- |
| `odom_topic`、`cmd_vel_topic` | `/leg_odom2`、`/cmd_vel` |
| `base_frame`、`odom_frame`、`map_frame` | base_footprint、odom、map |
| `sensor_frame` | camera_infra1_optical_frame |
| `left_image`、`right_image` | `/camera/camera/infra1/image_rect_raw`、`/camera/camera/infra2/image_rect_raw` |
| `left_camera_info`、`right_camera_info` | 对应 infra1/infra2 的 camera_info |
| `localization`、`use_nav2`、`use_viz` | false、false、false |
| `use_stereo_odometry`、`stereo_odom_topic` | false、`/vo` |
| `start_robot_state_publisher` | false |
| `description_package`、`description_file` | 空；启用 URDF 发布时都需提供 |
| `database_path` | `~/.ros/rtabmap_lite3_leg_d435i.db` |
| `nav2_params` | 本包 `config/nav.yaml` |
| `keepout_mask` | 空；非空时启动独立 mask map_server、filter info 与 lifecycle |

**建图模式 `localization=false` 的 RTAB-Map 启动参数带 `-d`，会重置所选数据库。这个入口没有 `delete_db_on_start` 参数。** 保存旧地图时先备份数据库；已有数据库重定位选择 `localization=true`。

新建地图（使用新的文件名）：

```bash
ros2 launch robot_slam_bringup nav.launch.py \
  database_path:=$HOME/.ros/rtabmap_new_mapping.db
```

已有地图重定位并启动导航：

```bash
ros2 launch robot_slam_bringup nav.launch.py \
  localization:=true use_nav2:=true \
  database_path:=$HOME/.ros/rtabmap_lite3_leg_d435i.db
```

更换机器人可覆盖接口和 frame：

```bash
ros2 launch robot_slam_bringup nav.launch.py \
  use_nav2:=true database_path:=$HOME/.ros/rtabmap_new_robot.db \
  odom_topic:=/robot/odom cmd_vel_topic:=/robot/cmd_vel \
  base_frame:=base_link odom_frame:=odom map_frame:=map \
  sensor_frame:=camera_infra1_optical_frame
```

这些参数同步覆盖 RTAB-Map 和 Nav2。`cmd_vel_topic` 覆盖恢复行为输出和速度平滑器最终输出；控制器到平滑器的内部链路保持原配置。

双目 VO 可这样切换：

```bash
ros2 launch robot_slam_bringup nav.launch.py \
  use_stereo_odometry:=true stereo_odom_topic:=/vo odom_topic:=/vo \
  database_path:=$HOME/.ros/rtabmap_stereo_vo.db
```

该 VO 的 `publish_tf=false`，不会自动补齐 `odom→base_footprint`。使用前配置与 `/vo` 一致的 TF 来源，避免重复发布。

## GO2/OpenVINS 入口

GO2 入口默认 `base_frame_id=base_link`、`planar_mode=true`、`imu_topic=/imu/data_raw`，**IMU 指 WIT，而不是 D435i 内置 IMU**。默认 `publish_camera_imu_tf=true` 发布已有 D435i—WIT 标定；外部 TF 已提供或设备安装变化时应处理重复/过期外参。切换到 D435i 内置 IMU需要对应的标定、frame、时间同步和配置。

该入口不启动传感器驱动。默认 `orientation_imu_topic=/rtabmap/unused_orientation_imu`，不把同一原始 IMU 当作已融合姿态再次用于 SLAM。公共管线可为 VIO 和 SLAM 分别指定图像及内参。

新建地图：

```bash
ros2 launch robot_slam_bringup go2_d435i_slam_nav2.launch.py \
  localization:=false navigation:=false delete_db_on_start:=true \
  database_path:=$HOME/.ros/rtabmap_go2_new.db
```

重定位与导航：

```bash
ros2 launch robot_slam_bringup go2_d435i_slam_nav2.launch.py \
  localization:=true navigation:=true delete_db_on_start:=false \
  database_path:=$HOME/.ros/rtabmap_go2_d435i.db
```

GO2/公共 OpenVINS 入口提供 `delete_db_on_start`，默认 true；保留数据库时显式 false。

## VINS-Fusion 入口

`d435i_wit_vins_rtabmap.launch.py` 默认查找 `vins` 包中的 WIT 双目配置，接收 `/imu/data_raw`，里程计输出接 `/odometry`。可配置传感器启动、VINS/RTAB-Map 延迟、曝光、增益和输出路径。此前本板 OpenVINS/RTAB-Map 构建没有编译 VINS-Fusion；使用前另行准备并核对标定。

各入口不能同时争用相同里程计、TF 或底盘速度。本文的启动命令是使用说明，本次未执行硬件建图或导航。

## 三机器人选择

完整配置、实测外参填写、灵猫官方资料与增量编译说明见 [三机器人配置与切换](../../ROBOT_PROFILES.md)。

```bash
# 仅查看解析后的配置，不启动任何 ROS 节点。
ros2 launch robot_slam_bringup nav.launch.py robot:=lite3 print_config:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=go2 print_config:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao print_config:=true
```

启动时设置 `use_nav2:=true`；底盘驱动/桥、D435i 驱动及完整 TF 仍由外部提供。
启动参数显式传值高于机器人配置默认值；`robot_config:=...` 可指定自己的 YAML。
`--show-args` 显示兼容的原 Lite3 声明默认值，实际选中机器人的结果以 `print_config:=true` 为准。
模型发布默认关闭；GO2 可启用已有描述包，灵猫使用固定官方资产的 `cyvet_description` ROS 2 安装包装。
灵猫 URDF 原根为 `BASE_LINK`，仅在启用模型发布时为其添加 `base_link` 零位姿命名别名；几何、关节名和原始文件不改动。
三份 `sensor_mount.xyz/rpy` 都不填假数值；有外部 TF 时保持 `publish_sensor_tf:=false`。

## 当前回环与重定位参数（2026-10-12）

`nav.launch.py` 的建图与定位两种模式、三套机器人配置共用这组试调起点：

| 参数 | 当前配置 |
| --- | --- |
| `Rtabmap/LoopThr`、`RGBD/AggressiveLoopThr`、`Rtabmap/LoopRatio` | 0.15、0.10、0 |
| `VhEp/Enabled`、`RGBD/OptimizeMaxError` | false、2.5 |
| `Vis/MinInliers`、`Vis/PnPReprojError`、`Vis/Iterations` | 20、2.0、300 |
| `Vis/BundleAdjustment`、`Vis/PnPRefineIterations` | 1、0 |
| `Vis/MinInliersDistribution` | 0.002（归一化二维内点 PCA 第二特征值） |
| `Kp/GridRows`、`Kp/GridCols`、`Kp/BadSignRatio` | 3、3、0.35 |
| `Kp/MaxFeatures`、`Vis/MaxFeatures` | 600、800 |
| `Kp/MinDepth`、`Kp/MaxDepth` | 0、0 |
| `Vis/MinDepth`、`Vis/MaxDepth`、`Grid/RangeMax` | 0.1、6.0、4.0 米 |

主 SLAM 的 `odom_frame_id` 仍使用非空 `odom_frame`，保持 **TF 获取位姿**。
即使 launch 字典中写有 `subscribe_odom=true`，ROS 封装在非空
`odom_frame_id` 下仍走 TF 路径。当前里程计没有可信协方差，未改成消息位姿输入，
也未凭空调整 `odom_tf_linear_variance` / `odom_tf_angular_variance`。
后续按实测误差分别校核三台机器人的方差。

这组参数是源码分析后的工程起点，尚未做 D435i 实机回访和错误地点测试。
PnP/BA、20 内点、2 像素重投影及图优化误差检查继续生效。
旧数据库已保存的特征不会随 Kp 网格设置自动重新生成；现有地图可以先回放比较。

修改主源码后，按 [增量构建说明](../../ROBOT_PROFILES.md) 同步到构建工作副本，
重新安装 `robot_slam_bringup`；本轮仅重建这个 Python 启动包。
应用记录、监控脚本、备份和检查报告在 `out/rk3588-loop-tuning-20261012`。
已运行的节点需要重新启动后才会读取新参数；不会在线更改正在运行的节点。
