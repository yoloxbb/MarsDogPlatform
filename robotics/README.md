# robotics 目录功能总览

核对日期：2026-10-12。本文以本目录的源码、package.xml、launch 和配置为准；描述代码具备的功能，不代表已通过板端运动测试。

`robotics` 是 MarsDogPlatform 的 ROS 2 机器人侧代码，负责传感器数据、建图导航、点位任务、人体三维定位和通用局部运动/UWB 跟随避障。目前有 **10 个自有 ROS 包**，全部位于 `ros2/src`。总仓库的语音、视觉识别、任务仲裁、动作执行和底盘 SDK 位于其他目录。

## 目录与包

```text
robotics/
├── README.md                  # 本总览
└── ros2/
    ├── README.md              # 构建、依赖和环境加载
    └── src/
        ├── stereo_v4l2_camera/
        ├── wit_imu/
        ├── robot_slam_bringup/
        ├── stereo_slam_legacy_bringup/
        ├── behavior_ext_plugins/
        ├── waypoint_nav/
        ├── person_3d_localization/
        ├── go2_uwb_local_follow/
        ├── go2_uwb_behavior/
        └── robot_local_motion/
```

| 包 | 主要功能 | 入口与说明 |
| --- | --- | --- |
| `stereo_v4l2_camera` | 读取一个左右拼接的 V4L2 双目设备，拆成左右灰度图并发布 CameraInfo | [说明](ros2/src/stereo_v4l2_camera/README.md)；`stereo_v4l2_camera.launch.py` |
| `wit_imu` | 读取 WIT 串口加速度和角速度，发布原始及低通滤波 IMU | [说明](ros2/src/wit_imu/README.md)；`wit_imu.launch.py` |
| `robot_slam_bringup` | 组合 RTAB-Map、外部底盘里程计或 OpenVINS/VINS-Fusion，以及可选 Nav2 | [说明](ros2/src/robot_slam_bringup/README.md)；主要入口 `nav.launch.py` |
| `stereo_slam_legacy_bringup` | 保留双目 VO + EKF 融合、旧 OpenVINS 建图等兼容入口 | [说明](ros2/src/stereo_slam_legacy_bringup/README.md) |
| `behavior_ext_plugins` | Nav2 自由空间脱困插件；独立 FollowPath 恢复行为树执行器 | [说明](ros2/src/behavior_ext_plugins/README.md) |
| `waypoint_nav` | 将地点 ID/名称或随机目标交给 Nav2；持久化、查询、取消和恢复锁管理 | [说明](ros2/src/waypoint_nav/README.md)；[协议](ros2/src/waypoint_nav/docs/INTERFACE.md) |
| `person_3d_localization` | bbox + 对齐深度 + TF → 人体三维点与保持安全距离的固定导航目标 | [说明](ros2/src/person_3d_localization/README.md)；[接口](ros2/src/person_3d_localization/docs/UPPER_LAYER_INTERFACE.md) |
| `go2_uwb_local_follow` | UWB 适配、双目障碍投影、滚动障碍地图、自研 MPPI 局部速度规划 | [说明](ros2/src/go2_uwb_local_follow/README.md) |
| `go2_uwb_behavior` | 为上述局部链路提供跟随、单次随机漫游、环绕一周三个互斥 Action | [说明](ros2/src/go2_uwb_behavior/README.md)；[接口](ros2/src/go2_uwb_behavior/docs/UPSTREAM_API.md) |
| `robot_local_motion` | 默认关闭的通用局部移动、接近、跟随、环绕、探索、转向任务，按任务传参并复用原 MPPI | [接口与仿生场景参数指南](ros2/src/robot_local_motion/README.md)；`local_motion.launch.py` |

## 四条功能链路

### 建图与地图导航

```text
D435i 校正双目图像 + CameraInfo + TF
                   + 外部 /leg_odom2
                   ↓
robot_slam_bringup/nav.launch.py
                   ↓
RTAB-Map → /map、map→odom、局部障碍点云
                   ↓（use_nav2:=true）
Nav2 全局规划、局部控制、恢复、速度平滑 → /cmd_vel → 外部底盘桥接
```

主要入口默认使用 Lite3 的 `/leg_odom2`，不要求 OpenVINS 参与，也不启动传感器驱动。可选双目 VO 输出 `/vo`，但其 `publish_tf=false`；切换输入后仍需外部提供一致的 `odom→base_footprint` TF。

GO2/OpenVINS 入口使用 RTAB-Map 的 `Odom/Strategy=10` 后端，默认接 **WIT `/imu/data_raw`**，并带有特定安装标定的相机/IMU TF。旧兼容 D435i 入口默认接 `/camera/camera/imu`。这些入口的标定、话题和机身 frame 不能混用。VINS-Fusion 入口另外需要 `vins` 包。

当前 `nav.yaml` 使用 Smac Hybrid 全局规划、Constrained Smoother、Nav2 MPPI、STVL 局部障碍层以及 `BackUpTwzFree` 脱困。它与 UWB 链路中的自研 MPPI 是两套不同控制器。行为树文件名虽然包含 `no_backup`，内容仍有 `BackUp` 恢复；主要行为树在目标变化或恢复后重规划，不周期重规划。

### 点位与随机导航任务

```text
外部 MarsDogAction → /navigation/task（VoiceTask）
                   ↓
waypoints.yaml 精确匹配 / 实时 /map 随机采样
                   ↓
Nav2 /navigate_to_pose → 状态 JSON + SQLite 任务记录
```

支持 `goto_place`、`query`、`cancel`、人工 `release_recovery`。地点编辑网页不在本包内；普通地点使用稳定 ID，`11`/`K` 是同一个随机导航保留入口。取消受理不等于导航已停止；未知 Nav2 终态会保留恢复锁。

### 走向检测到的人

```text
外部视觉节点的原图 bbox + 时间戳
                   + 对齐深度、CameraInfo、历史 TF
                   ↓
/person_3d_localization/locate_from_bbox
                   ↓
person_point + navigation_goal + navigation_required
                   ↓
上层判断响应后决定是否发送 Nav2 Goal
```

本包不识别人、不跟踪人，也不会自行启动导航。已在安全距离内时 `navigation_required=false`，上层应保持当前位置。

### UWB 跟随、单次漫游与环绕

```text
外部 UWB 驱动 → UWB 目标适配 ────────────────┐
D435i 双目 → 视差 → 障碍投影 → 滚动地图 ──┤
外部 /leg_odom2 位姿与速度 ────────────────┤
上层 FollowUwb / RandomRoam / OrbitUwbOnce ─┤
                                         ↓
行为控制器名义速度 → 自研 MPPI → 行为安全门控 → /cmd_vel
```

这条链路使用局部里程计和滚动障碍点云，不要求 SLAM、全局地图或 Nav2。滚动地图是二维障碍缓存，不是 OccupancyGrid 全局路径规划器。普通规划不倒车，紧急倒退由独立状态机负责。

统一入口 `behavior_follow_roam.launch.py` 默认 IDLE，按 Action 门控开启感知；Follow/Orbit 进入最终停车时关闭，RandomRoam 结束时关闭。当前配置 `publish_idle_velocity=false`，空闲时不持续发零；活动 UWB Action 期间仍需由上层保证最终速度控制权唯一。`STOP` 只锁存本行为控制器，不会自动锁住其他 `/cmd_vel` 来源。取消终态不单独证明物理停稳，具体限制见接口文档。

## 外部依赖与构建产物

| 依赖 | 位置或来源 | 用途 |
| --- | --- | --- |
| ROS 2 Humble | `/opt/ros/humble` 或已验证的原生依赖环境 | 消息、TF、构建工具等 |
| OpenVINS / RTAB-Map / rtabmap_ros | 总仓库 `.external`；本板独立构建在 `out/rk3588-openvins`、`out/rk3588-rtabmap` | 视觉惯性里程计和 SLAM |
| `uwb_aoa_pkg` | 总仓库 `.external/uwb` | 厂家消息定义及可选 ARM64 驱动 |
| `marsdog_voice_interaction` | 总仓库 `modules/voice` | `waypoint_nav` 复用的 VoiceTask 接口 |
| RealSense、Nav2、STVL、机器人描述、VINS-Fusion | 外部 ROS 包 / 总仓库对应外部源码 | 按所选 launch 安装、编译和加载 |
| 底盘桥接、机器人里程计、安装标定 | 机器人部署环境 | 接收速度、发布位姿与 TF |

构建方法见 [ROS 2 构建说明](ros2/README.md)。源码目录不必有 `build`；本项目把构建、安装和日志集中放在总仓库 `out` 下。

2026-10-11 的板端 OpenVINS、RTAB-Map/rtabmap_ros 编译验证，不等于本目录 9 个包及其全部硬件依赖已集成验证。LibTorch/SuperPoint、GTSAM 已编译进 RTAB-Map，但当前 launch 仍使用传统特征 `Kp/DetectorStrategy=8`、g2o `Optimizer/Strategy=1`；编译能力不会自动改变运行算法。D435i 实机建图与导航仍需单独测试。同日后续已在 `out/rk3588-navigation` 源码构建 Nav2 1.1.20（含 MPPI）、STVL 2.3.4、用户提供的 GO2 描述包及本目录 9 个包，并完成无硬件插件/参数配置检查。运行时加载 `out/rk3588-navigation/use-navigation.sh`；VINS-Fusion 本次按要求跳过。详见 [导航构建与使用](ros2/NAVIGATION_BUILD.md)。

## 使用前必须区分的配置

- `nav.launch.py` 的建图分支带 `-d`，会重置所选数据库；保存已有地图时先备份，重定位使用 `localization:=true`。
- UWB 统一入口和旧完整局部跟随入口的 `enable_motion` 默认均为 `true`；只检查接口时显式传 `false`。
- V4L2 驱动发布 `/cam0`、`/cam1` 原始图，D435i 入口订阅 RealSense 校正图；需要不同的驱动、标定和校正链路。
- WIT 原始 IMU 没有有效姿态四元数；低通滤波不等于姿态融合。GO2 默认 WIT 标定不能直接用于 D435i 内置 IMU。
- Nav2、UWB 控制、动作执行、遥控同时存在时，需要部署层仲裁速度控制权；本目录没有通用 `/cmd_vel` 多路仲裁器。

2026-10-11 的目录核对只更新文档。2026-10-12 新增了默认关闭的通用局部运动包与可选 Action 适配器，保留旧入口、旧动作路由和标定；无硬件编译/通信验证记录见新包指南，未启动实机运动测试。

## 三机器人统一导航配置

Lite3、GO2 和宇泛灵猫现在统一使用 `robot_slam_bringup/nav.launch.py`，通过 `robot:=lite3|go2|lingmao` 选择配置，共用 MPPI、STVL、Smac Hybrid 和 Constrained Smoother。未指定 robot 时保留 Lite3 默认参数。详见 [三机器人配置与切换指南](ros2/ROBOT_PROFILES.md)。
