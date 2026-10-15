# robot_slam_bringup 建图与导航入口

核对日期：2026-10-14。本包是 Python launch/配置组合包，主要入口 `nav.launch.py` 通过 `robot:=lite3|go2|lingmao` 选择 Lite3、GO2 或宇泛灵猫配置，使用外部里程计和 D435i 双目启动 RTAB-Map，并可启动公共 MPPI/STVL 导航；另外保留历史 GO2/OpenVINS 和 VINS-Fusion 入口。

## 地图完整性与只读定位

2026-10-13：统一入口 `nav.launch.py` 的 RTAB-Map 处理频率改为 1 Hz，
`Rtabmap/TimeThr=0`、`Rtabmap/MemoryThr=0`，不因时间或节点数量预算清退工作记忆。
建图时内存和处理耗时仍随地图增长，需要持续监测。

`localization=true` 使用 `Mem/IncrementalMemory=false`、
`Mem/LocalizationReadOnly=true`、`Mem/LocalizationDataSaved=false` 和
`Mem/InitWMWithAllNodes=true`，加载历史节点并以只读方式使用已有数据库。
本次最后定位位置不会写回，下一次启动需重新定位或提供正确初始位姿。
只读模式应使用连通地图；不连通的多会话需要先检查整理。
2026-10-12 调整了处理频率、记忆裁剪和定位只读参数。2026-10-13 增加 Nav2 里程计 QoS 转发，并允许静止定位执行视觉候选几何验证；数据库日志/同步、退出超时及建图 `-d` 行为沿用原配置。

## 文件与算法

| 文件 | 功能与默认输入 |
| --- | --- |
| `launch/nav.launch.py` | RTAB-Map 建图/定位，可选 VO、Nav2、可视化与 keepout；默认包含独立 TF 入口 |
| `launch/robot_tf.launch.py` | 独立机身模型、里程计 relay、相机/UWB 安装 TF；不启动建图、导航或传感器驱动 |
| `launch/go2_d435i_slam_nav2.launch.py` | GO2 frame 配置 + OpenVINS/RTAB-Map；可选定位和 Nav2 |
| `launch/openvins_rtabmap.launch.py` | RTAB-Map `stereo_odometry` 使用 `Odom/Strategy=10` 的 OpenVINS 后端，再接 RTAB-Map SLAM；不是单独启动 `ov_msckf` |
| `launch/d435i_wit_vins_rtabmap.launch.py` | 外部 `vins` 视觉惯性里程计 + RTAB-Map；`start_sensors=true` 时启动 RealSense/WIT |
| `config/nav.yaml` | 公共 Nav2（未覆盖时为原 Lite3 默认值）：Smac Hybrid + Constrained Smoother + Nav2 MPPI + STVL + 自由空间脱困 |
| `config/openvins_rtabmap.yaml` | OpenVINS 后端及 RTAB-Map 参数 |
| `config/go2_nav2.yaml` | 历史 GO2 DWB 配置；新三机器人入口均使用公共 nav.yaml |
| `config/robots/*.yaml` | 三套机器人专属接口、轮廓、速度、安装外参/灵猫初版估计和来源记录 |
| `robot_slam_bringup/odometry_tf_relay.py` | 可选 Odometry → TF；灵猫分离 base_footprint 与机身高度/姿态 |
| `config/navigate_to_pose_no_backup.xml` | 单点导航：目标变化或恢复后重规划；实际包含 `BackUp` 恢复 |
| `config/navigate_through_poses_no_backup.xml` | 多点导航行为树，恢复行为以内容为准 |
| `robot_slam_bringup/d435i_extrinsics_relay.py` | IMU frame 转发和右目基线 CameraInfo 修正辅助节点；仅由引用它的入口使用 |

当前主要入口和公共 OpenVINS 配置使用传统特征 `Kp/DetectorStrategy=8`、g2o `Optimizer/Strategy=1`。编译打开 GTSAM、LibTorch/SuperPoint 不会自动切换这些参数；SLAM 特征和图优化默认值保持原设置；新增 GO2/灵猫 profile 的导航使用公共 MPPI/STVL。

## 构建与前提

按 [公共构建说明](../../README.md) 准备依赖、选择 `robot_slam_bringup` 并加载安装环境。本板当前完整产物可直接加载 `out/rk3588-navigation/use-navigation.sh`，其中包含 RTAB-Map/OpenVINS、Nav2、STVL 和本启动包；详见 [导航构建与使用](../../NAVIGATION_BUILD.md)。VINS-Fusion 本次跳过。

主要 `nav.launch.py` **不启动 RealSense、WIT 或底盘驱动**。先由部署层提供图像、CameraInfo 和底盘里程计；TF 所有者按所选 profile 配置，灵猫由本包 relay 和模型补齐相应边。该文件直接导入 Nav2 launch 工具并查找 `nav2_bringup`，因此即使 `use_nav2=false`，解析 launch 也需要相应 Nav2 包。完整 `nav.yaml` 还需要 MPPI、Smac、Constrained Smoother、STVL、DenoiseLayer 和本仓库 `behavior_ext_plugins`；插件兼容性按实际 Nav2 版本核对。

## 独立 TF 启动

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 launch robot_slam_bringup robot_tf.launch.py \
  robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml"
~~~

TF 入口直接复用所选 profile 的话题、frame、模型、机身高度和传感器外参，可用 `print_config:=true` 只查看配置；无需加载 nav2_bringup 或 nav2_common，也不创建/清空 RTAB-Map 数据库。`map→odom` 仍由 RTAB-Map 发布，相机内部/光学 TF 仍由相机驱动发布。

nav.launch.py 默认 `start_tf:=true` 包含此入口；TF 已在独立终端运行时，导航命令加 `start_tf:=false`，且两端使用相同机器人配置和 TF 参数覆盖。旧 `frames_only:=true` 保持兼容。TF 固定安装边可以独立发布，动态里程计/机身边仍需有效外部 Odometry；不自动连接底盘或启动运动。

## 主要入口默认参数（未指定 robot 时为 Lite3）

| 参数 | 默认值 |
| --- | --- |
| `odom_topic`、`cmd_vel_topic` | `/leg_odom2`、`/cmd_vel` |
| `nav2_odom_topic` | 默认跟随 `odom_topic`；灵猫 profile 为 `/odom_nav` |
| `base_frame`、`odom_frame`、`map_frame` | base_footprint、odom、map |
| `sensor_frame` | camera_infra1_optical_frame |
| `left_image`、`right_image` | `/camera/camera/infra1/image_rect_raw`、`/camera/camera/infra2/image_rect_raw` |
| `left_camera_info`、`right_camera_info` | 对应 infra1/infra2 的 camera_info |
| `localization`、`use_nav2`、`use_viz` | false、false、false |
| `start_tf` | true；TF 已单独运行时设 false |
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

RTAB-Map 的 `/map` 保留最后一张地图。公共 `config/nav.yaml` 已启用 `static_layer.map_subscribe_transient_local: True`，确保 Nav2 启动较晚、定位时地图未变化也能接收缓存；修改后需重启导航。电脑 RViz 的 Map 同样使用 `Transient Local`，完整启动和导航界面配置见 [远程可视化指南](../../REMOTE_VISUALIZATION.md)。

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

frame 等公共参数同步覆盖 RTAB-Map 和 Nav2。`odom_topic` 保留原始输入，`nav2_odom_topic` 只重写 Nav2 的里程计订阅，不改变 RTAB-Map 的 TF 位姿来源。`cmd_vel_topic` 覆盖恢复行为输出和速度平滑器最终输出；控制器到平滑器的内部链路保持原配置。

灵猫原始 /odom 使用 Best Effort，而 Nav2 里程计订阅要求 Reliable。现有 `odometry_tf_relay` 的可选 `output_odom_topic` 在完成有效输入检查并发送 TF 后，可靠转发原始 Odometry；空值关闭转发，输入/输出解析到同一话题会拒绝配置，避免消息回环。launch 仅在 nav2_odom_topic 与 odom_topic 不同时配置转发。消息 header、frame、pose、twist、covariance 全部保持原样，未伪造协方差。

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

各入口不能同时争用相同里程计、TF 或底盘速度。2026-10-13 只对当前灵猫主入口完成了实机导航链路验证；历史 GO2/OpenVINS 与 VINS-Fusion 入口未在本次运行。

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
Lite3/GO2 的模型发布保持默认关闭；灵猫 profile 默认启用 cyvet_description 模型与相机分支。
灵猫使用 `base_footprint` 导航、`base_link` 表达物理机身。relay 分开发平面位姿和用户 2026-10-14 校正后的 `0.36 m` 站姿高度。
运行时 URDF 将官方机身根 `BASE_LINK` 统一重命名为 `base_link`，四条腿的父链接同步更新；不再发布大写机身坐标系或零位移别名关节。按实测 bridge 关节名称设置别名，并添加相机固定关节；原官方文件不改动。
相机初版为 `xyz=[0.289,0,0.114]`、`rpy=[0,0,0]`，是用户授权的模型估计，不是实测标定。
灵猫 `uwb_mount` 使用用户提供的相对相机偏移 `[-0.04,0,-0.05] m`、零相对旋转，生成 `camera_link→uwb_link` 固定关节。默认由同一 robot_state_publisher 发布；关闭模型或相机安装由外部提供时，入口使用独立静态发布器。未提供 uwb_mount 的其他机器人维持原行为。
Lite3/GO2 外参仍待测；有正确外部相机 TF 时设置 `publish_sensor_tf:=false`。
独立 `robot_tf.launch.py` 可只发布模型与 TF；旧 `frames_only:=true` 保持兼容；当前个人配置在 `~/.config/marsdog/robots/lingmao.yaml`，
需通过 `robot_config:=...` 使用它。完整 TF 所有权、当前运行与调整步骤见三机器人指南。

## 当前回环与重定位参数（2026-10-13）

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

定位参数单独将 `RGBD/LinearUpdate`、`RGBD/AngularUpdate` 设为 `0`；建图维持 `0.1` m / `0.1` rad。核心源码的 smallDisplacement 分支会跳过全局候选的几何验证；定位关掉这两个位移门限后，静止也可在 1 Hz 检测频率下验证候选，未放宽上述视觉/图优化阈值。本次静止定位 accepted_hypothesis_id 为 81/82，内点 36～47；只读定位的 `Loop/Last_id=0` 不能单独作为重定位失败依据。

主 SLAM 的 `odom_frame_id` 仍使用非空 `odom_frame`，保持 **TF 获取位姿**。
即使 launch 字典中写有 `subscribe_odom=true`，ROS 封装在非空
`odom_frame_id` 下仍走 TF 路径。当前里程计没有可信协方差，未改成消息位姿输入，
也未凭空调整 `odom_tf_linear_variance` / `odom_tf_angular_variance`。
后续按实测误差分别校核三台机器人的方差。

这组参数是源码分析后的工程起点。当前地图已经验证静止重定位及 6 个用户发送的实机导航目标，但未做错误地点重定位和系统性的回访精度测试。
PnP/BA、20 内点、2 像素重投影及图优化误差检查继续生效。
旧数据库已保存的特征不会随 Kp 网格设置自动重新生成；现有地图可以先回放比较。

修改主源码后，按 [增量构建说明](../../ROBOT_PROFILES.md) 同步到构建工作副本，
重新安装 `robot_slam_bringup`；相关修改仅需重建这个 Python 启动包。
应用记录、监控脚本、备份和检查报告在 `out/rk3588-loop-tuning-20261012`。
常规源码/配置更新后，已运行节点需重新启动。2026-10-13 用户已重启导航，静止定位两个门限另经参数服务即时应用并已安装到源码；下次启动会自动读取。

本次 22 项配置/TF 测试、隔离 Domain 86 的真实 ROS QoS 传输测试以及平台 `tools/dev.py check` 均通过。隔离传输测试覆盖 Best Effort 输入到 Reliable 输出、原消息完整保留及无效四元数不转发；未向实机发送速度。实机由用户通过 RViz 发目标，6 个均返回状态 4（Succeeded），一次进度检查失败后由 Nav2 恢复成功。证据见 `out/rk3588-remote-visualization/navigation-readiness-result-2026-10-13.json`。

## 起点占用时的移动脱困

统一入口使用自定义 BackUpTwzFree，灵猫也使用该插件；灵猫脱困横移已按用户要求开启（enable_strafe=true），正常导航模型保持原配置。只在新鲜全局代价地图中当前机器人中心格为 253/254 时允许移动脱困。起点自由但目标无全局可达路径时，清局部图并等待后重规划一次，仍失败就结束导航，不移动脱困。起点占用时可搜索自由空间移动；离开占用区后目标仍无路可达，不再继续移动脱困。未知、图外、过期地图和缺失 TF 都不授予移动条件，规划失败的空路径不再交给 FollowPath。

## 清图后的观测与地图等待

统一导航树使用同一 BT 动态库中的 `WaitForFreshCostmap` 替代固定 1 s 等待。清图服务成功返回后才开始等待；移动脱困成功后也执行相同等待，然后才能重新规划。等待放在 `RoundRobin` 外，超时返回失败并结束本次导航恢复，不会因超时切换到移动脱困。

放行需要依次观察到：至少一路 `/local_grid_obstacle` 或 `/local_grid_ground` 的源时间戳晚于本次等待起点；之后局部地图 `published_footprint` 的新时间戳表明完成一次地图更新；之后收到完整的 `local_costmap/costmap_raw` 快照，并且观测坐标到地图坐标的 TF 可用。旧数据、未来时间戳、无效地图和上一轮恢复的数据不能复用。RTAB-Map 省略为空的点云类别，因此不要求两路同时发布；真正发布的有效空点云也可接受。

```yaml
bt_navigator:
  ros__parameters:
    recovery_observation_timeout: 5.0
    recovery_observation_topics: ["/local_grid_obstacle", "/local_grid_ground"]
    recovery_fresh_costmap_topic: local_costmap/costmap_raw
    recovery_costmap_update_topic: local_costmap/published_footprint
```

超时使用单调时钟，ROS 时间停住也会退出；取消会清理本轮状态。5 s 只计算动作成功后的数据等待，不包含原清图服务和移动动作本身的时限。每次新恢复都重新获取观测。超时日志列出收到的观测和是否观察到地图更新。

此检查利用当前 Nav2 Humble 的更新完成事件和发布时间顺序，不是 STVL 对某一帧点云逐点处理的确认接口，也不是定位正确性判据。全局地图没有清空，此处等待的是局部代价地图。独立示例执行器的历史行为树未改。
