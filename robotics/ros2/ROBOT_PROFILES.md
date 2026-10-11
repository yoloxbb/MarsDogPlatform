# Lite3、GO2、宇泛灵猫统一导航配置与切换

核对与实现日期：2026-10-11。三个机器人均使用 `robot_slam_bringup/nav.launch.py`，共用 RTAB-Map 双目建图、MPPI、STVL、Smac Hybrid、Constrained Smoother 和现有行为树。配置切换不会启动底盘驱动、申请控制权或切换机器人的运动模式。

## 选择机器人

先加载现有板端安装环境：

```bash
export MARSDOG_ROOT="${MARSDOG_ROOT:-$HOME/MarsDogPlatform}"
source "$MARSDOG_ROOT/out/rk3588-navigation/use-navigation.sh"

# 只检查配置：不启动任何 ROS 节点、相机、底盘或 Nav2。
ros2 launch robot_slam_bringup nav.launch.py robot:=lite3 print_config:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=go2 print_config:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao print_config:=true
```

底盘/相机与 TF 已由外部提供、地图准备好之后，用同一入口重定位与导航：

```bash
ros2 launch robot_slam_bringup nav.launch.py robot:=lite3 localization:=true use_nav2:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=go2 localization:=true use_nav2:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao localization:=true use_nav2:=true
```

这些导航命令供用户实际部署时执行，本次验证没有运行它们。各机器人使用独立数据库。需要建新图时使用 `localization:=false use_nav2:=false`，并用 `database_path:=...` 指定新的文件。**原主入口的建图模式仍传入 `-d`，会重置所选数据库；已有地图必须选择 `localization:=true`。**

未传 `robot` 时仍为 Lite3，原默认话题、轮廓、速度、TF 所有权、默认不启用 Nav2 等行为保留。

## 三套参数

| 参数 | Lite3 | GO2 | 灵猫 Cyvet |
| --- | --- | --- | --- |
| 配置文件 | `config/robots/lite3.yaml` | `config/robots/go2.yaml` | `config/robots/lingmao.yaml` |
| 基座 frame | `base_footprint` | `base_link` | `base_link` |
| 外部里程计输入 | `/leg_odom2` | `/odom` | 官方 bridge `/odom` |
| 最终速度输出 | `/cmd_vel` | `/cmd_vel` | 官方 bridge `/cmd_vel` |
| 初始轮廓长×宽 | 0.68×0.38 m，原配置 | 0.76×0.44 m，原配置 | 0.76×0.46 m，官网尺寸推导的保守初值 |
| MPPI 前进/后退限速 | 0.50 / 0.50 m/s | 0.40 / 0.20 m/s | 0.30 / 0.15 m/s |
| MPPI 转向限速 | 1.20 rad/s | 0.80 rad/s | 0.60 rad/s |
| 默认 odom→base TF | 由外部发布 | 由外部发布 | 本包根据官方 Odometry 消息转发 |
| 描述包 | 未配置 | 已有 `go2_description` | 官方资产安装包装 `cyvet_description` |
| 数据库 | `rtabmap_lite3_leg_d435i.db` | `rtabmap_go2_d435i_mppi.db` | `rtabmap_lingmao_d435i_mppi.db` |

数据库默认存放在当前用户 `~/.ros/`。这些速度是项目导航限值，不能当作机器人厂家性能参数。Lite3 精确保留旧值；GO2 的新 MPPI 速度范围采用原速度平滑器的范围，原 DWB 控制器本身不配置后退轨迹。灵猫速度为本项目保守初值，没有实机调优验收。

三套算法共用 `config/nav.yaml`，机器人 YAML 只覆盖差异。该公共文件保留原 Lite3 值作为兼容基线。GO2 原来的 `go2_d435i_slam_nav2.launch.py`、DWB 配置及 OpenVINS/VINS 入口保留，但不属于新的三机器人统一导航路径。

## 底盘与里程计边界

`nav.launch.py` 订阅的是 **标准 `nav_msgs/msg/Odometry`**，输出的是 **`geometry_msgs/msg/Twist`**，不包含厂商通信协议转换。

- Lite3 保持 `/leg_odom2`，外部里程计发布器同时负责 `odom→base_footprint`。
- GO2 使用 `/odom`，需要底盘桥或独立里程计前端发布与 `base_link` 一致的消息和 TF。新的统一入口不会自动启动旧 GO2 OpenVINS 管线。若仍用 OpenVINS，请只提供里程计前端，避免同时运行两个 RTAB-Map 建图节点。
- 灵猫按官方 ROS 2 Motion Bridge 的标准话题与 frame 配置。当前固定版本的桥发布 `/odom`，没有 TF 广播器，因此该 profile 默认启用本包 `odometry_tf_relay`。转发保留原消息时间戳和位姿，不积分速度、不猜测里程计；frame 不匹配、零时间戳或非法四元数会被拒绝。

每条 `odom→base` TF 必须只有一个发布者。若灵猫的其他软件已经发布它，传 `publish_odom_tf:=false`；若 GO2 的外部来源只发消息且确定没有 TF，可传 `publish_odom_tf:=true`。

## 灵猫官方资料与限制

来源链：[宇泛官网产品页](https://uniubi.com/shop/buy?product=air)链接到[官方 GitHub 组织](https://github.com/uniubi-ai)，其中维护开发文档、ROS 2 bridge 和 Cyvet 模型。

| 官方来源 | 本次记录版本 | 使用的信息 |
| --- | --- | --- |
| [产品页](https://uniubi.com/shop/buy?product=air) | 2026-10-11 核对 | 站立 672×355×432 mm、趴地 718×410×178 mm，产品标称速度 0～3 m/s |
| [官方开发文档](https://github.com/uniubi-ai/uniubi-docs/tree/939d9c7286c35089c3464a2fbd04e67914b510a1) | `939d9c7286c35089c3464a2fbd04e67914b510a1` | 机体右手坐标系：X 前、Y 左、Z 上；ROS 桥接入与控制边界 |
| [官方 ROS 2](https://github.com/uniubi-ai/uniubi_ros2/tree/6e6edc057e4e232659566f0dc05e1b18393d5e1b) | `6e6edc057e4e232659566f0dc05e1b18393d5e1b` | `/odom`、`/cmd_vel`，`odom/base_link`；源码中只发布里程计消息 |
| [官方描述资产](https://github.com/uniubi-ai/uniubi_robot_description/tree/8aa1acba3cde0ec2dfc2e1dc2b4fa609a06087c9) | `8aa1acba3cde0ec2dfc2e1dc2b4fa609a06087c9` | `robots/cyvet/urdf/cyvet.urdf`、mesh；原根名称 `BASE_LINK` |

灵猫矩形轮廓是由官网整体长宽推导的 **工程初值**，并给出约 20 mm 以上的外形余量。官网尺寸没有给出所有步态、载荷和腿部摆动下的动态碰撞包络；确认实际版本及最大足端伸出范围后再调整。官网当前产品参数和描述资产也可能对应不同交付版本，以实物为准。不能把厂家最大 3 m/s 填进室内导航限速。

官方桥启动后不会自动申请控制权；`/cmd_vel` 不能代替控制权申请和进入 Walk 状态。桥、控制状态和退出释放流程应按[固定版本 ROS 2 文档](https://github.com/uniubi-ai/uniubi_ros2/blob/6e6edc057e4e232659566f0dc05e1b18393d5e1b/README.zh-CN.md)执行，本次未新增控制协议或自动申请流程。该 bridge/message/client 包属于底盘接入依赖，本次配置任务没有安装或连接它们。

固件 `Cyvet-V1.00.002` 及以上使用官方当前 main；更早固件应选择官方 `Cyvet-V1.00.001` 标签对应的兼容接口。开发文档区分 Orin 本机接入（domain 1、`cerebellumServer`）和外部主机接入（domain 42、`robotServer`）。RK3588 作为外部主机时应按外部接入流程确认实际网络、设备 SN 和网卡。导航 launch 不改 `ROS_DOMAIN_ID`、RMW 或网卡配置。

## 每台机器首次填写相机安装外参

共享的 D435i 图像/CameraInfo 话题可以通过 launch 参数覆盖。三个机器的基座到相机的安装变换取决于实际安装位置，官网无法提供。每个 profile 都留有：

```yaml
sensor_mount:
  parent_frame: base_link  # Lite3 为 base_footprint
  child_frame: camera_link
  xyz: null  # 填写实测 [x, y, z]，单位 m
  rpy: null  # 填写实测 [roll, pitch, yaw]，单位 rad
```

如果已经有正确的外部 TF，保持 `publish_sensor_tf:=false`（默认）。否则在自己的 YAML 填写真实外参，再传 `publish_sensor_tf:=true`。未填写时启用会直接报错，不发布假的零位姿。若同时覆盖 `base_frame`，也应更新 `sensor_mount.parent_frame`。

本统一入口不发布旧 OpenVINS 文件中固定的 D435i→WIT IMU 外参，也不订阅 IMU。`use_stereo_odometry:=true` 仍是原来额外输出 `/vo` 的视觉里程计功能，默认不替代底盘里程计、不发布 TF。

## URDF 与模型发布

模型发布保持默认关闭：`start_robot_state_publisher:=false`。需要时可显式启用：

```bash
ros2 launch robot_slam_bringup nav.launch.py robot:=go2 start_robot_state_publisher:=true
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao start_robot_state_publisher:=true
```

灵猫官方资产仓不是 ament 包，本次用最小 `cyvet_description` 包装安装原资产，原 URDF/mesh 不修改。启动时将相对 mesh 引用转换为 package URI；按 profile 的明确配置，在原根 `BASE_LINK` 前添加 `base_link` 零位姿命名别名。它只是同一机体坐标的命名连接，不提供 D435i 安装外参。官方桥输出的关节名称与 URDF 的 `FL_ABAD_JOINT` 等名称需要实机核对，不能假设完全匹配。

## 保存自己的配置与优先级

优先级为：公共 `nav.yaml` → 所选机器人 `nav2_overrides` → 显式 launch 话题/frame 覆盖。机器人配置中的 launch 默认值不会覆盖命令行显式传值。

```bash
mkdir -p "$HOME/.config/marsdog/robots"
cp "$(ros2 pkg prefix --share robot_slam_bringup)/config/robots/lingmao.yaml" \
  "$HOME/.config/marsdog/robots/lingmao.yaml"
# 编辑自己的配置后，仅打印核对；绝对路径由当前 HOME 派生。
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml" print_config:=true
```

用户配置无需重新编译。修改源码目录中的包内 YAML、Python 或 launch 后，需要增量安装一次；不要直接修改 `out/.../install` 中的副本。`--show-args` 显示原 Lite3 的兼容声明默认值，所选机器人的解析值以 `print_config:=true` 的 `ROBOT_CONFIG` 输出为准。

## 增量构建与复现

源代码在 `$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup`，构建工作副本在 `$MARSDOG_ROOT/out/rk3588-navigation/source/robotics/robot_slam_bringup`。首次描述资产包装和监控构建脚本位于 `out/rk3588-robot-profiles/`，官方归档及 SHA256 记录也在该目录。

Windows 交付脚本统一保存在 `D:\work\scripts\rk3588-robot-profiles`，说明见 `D:\work\scripts\脚本使用说明.md`；配置快照位于 `D:\work\资料归档\配置快照\机器人导航`。这些本机交付资源不随 Git 仓库分发，首次安装灵猫描述资产时需取得完整脚本及对应归档。Windows 目录整理不改变上述板端执行位置。

```bash
export MARSDOG_ROOT="${MARSDOG_ROOT:-$HOME/MarsDogPlatform}"
# 修改主源码后同步工作副本，只覆盖本包；不要对整个 source 目录清理。
cp -a "$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup/." \
  "$MARSDOG_ROOT/out/rk3588-navigation/source/robotics/robot_slam_bringup/"
python3 "$MARSDOG_ROOT/out/rk3588-robot-profiles/prepare-cyvet-description.py"
python3 "$MARSDOG_ROOT/out/rk3588-robot-profiles/build-robot-profiles-monitored.py"
source "$MARSDOG_ROOT/out/rk3588-navigation/use-navigation.sh"
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao print_config:=true
```

该构建只选择 `robot_slam_bringup` 和资产安装包装 `cyvet_description`，不会重编 Nav2/RTAB-Map。仍从两任务开始监控，必要时降到一任务；单任务继续构建。

## 本次验证范围

2026-10-11 实现时的验证记录见 `out/rk3588-robot-profiles/verification.json`，不是每次提交自动重跑的结果。包括配置/TF 转换单元测试、已安装包的三套 print-only 启动、显式参数覆盖、非法 profile 和未知外参拒绝、官方 URDF/mesh 完整性，以及隔离 DDS 域内三套 Nav2 lifecycle 服务器仅 configure 到 inactive 的验证。TF relay 使用独立域和合成 Odometry 做传输验证。

在已安装 ROS 消息和 `cyvet_description` 的板端环境中，可以对源码重复运行无 DDS 通信的配置、消息转换和描述资产测试：

```bash
source "$MARSDOG_ROOT/out/rk3588-navigation/use-navigation.sh"
PYTHONPATH="$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup:${PYTHONPATH:-}" \
  python3 -B -m unittest discover \
  -s "$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup/test" -v
```

不启动相机、底盘桥或厂商控制客户端，不激活 Nav2、不发送导航目标，不验证实机建图、行走和避障效果。三份安装外参与灵猫设备接入信息仍需按实际机器填写。
