# Lite3、GO2、宇泛灵猫统一导航配置与切换

初次实现：2026-10-11；灵猫模型/坐标系更新：2026-10-12；导航链路验证：2026-10-13。三个机器人均使用 `robot_slam_bringup/nav.launch.py`，共用 RTAB-Map 双目建图、MPPI、STVL、Smac Hybrid、Constrained Smoother 和现有行为树。配置切换不会启动底盘驱动、申请控制权或切换机器人的运动模式。

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
| 导航基座 frame | `base_footprint` | `base_link` | `base_footprint` |
| 外部里程计输入 | `/leg_odom2` | `/odom` | 官方 bridge `/odom` |
| Nav2 里程计输入 | `/leg_odom2` | `/odom` | relay 转发的 Reliable `/odom_nav` |
| 最终速度输出 | `/cmd_vel` | `/cmd_vel` | 官方 bridge `/cmd_vel` |
| 初始轮廓长×宽 | 0.68×0.38 m，原配置 | 0.76×0.44 m，原配置 | 0.76×0.46 m，官网尺寸推导的保守初值 |
| MPPI 前进/后退限速 | 0.50 / 0.50 m/s | 0.40 / 0.20 m/s | 0.30 / 0.15 m/s |
| MPPI 转向限速 | 1.20 rad/s | 0.80 rad/s | 0.60 rad/s |
| 默认 odom→base TF | 由外部发布 | 由外部发布 | 本包分层发布 odom→base_footprint→base_link |
| 描述包 | 未配置 | 已有 `go2_description` | 官方资产安装包装 `cyvet_description` |
| 数据库 | `rtabmap_lite3_leg_d435i.db` | `rtabmap_go2_d435i_mppi.db` | `rtabmap_lingmao_d435i_mppi.db` |

数据库默认存放在当前用户 `~/.ros/`。这些速度是项目导航限值，不能当作机器人厂家性能参数。Lite3 精确保留旧值；GO2 的新 MPPI 速度范围采用原速度平滑器的范围，原 DWB 控制器本身不配置后退轨迹。灵猫速度为本项目保守初值，没有实机调优验收。

三套算法共用 `config/nav.yaml`，机器人 YAML 只覆盖差异。该公共文件保留原 Lite3 值作为兼容基线。GO2 原来的 `go2_d435i_slam_nav2.launch.py`、DWB 配置及 OpenVINS/VINS 入口保留，但不属于新的三机器人统一导航路径。

## 底盘与里程计边界

`nav.launch.py` 仍接标准 `nav_msgs/msg/Odometry`，输出标准 `geometry_msgs/msg/Twist`，不申请运动控制权。
Lite3 与 GO2 默认行为保持原样。灵猫当前 bridge 的原始 `/odom` 是 `odom/base_link`，话题及 child_frame_id 不改动。
同一个 `odometry_tf_relay` 将其平面位置/yaw 发布为 `odom→base_footprint`，再发布 `base_footprint→base_link`。
Nav2 与 RTAB-Map 使用 `base_footprint`，RTAB-Map 继续通过 TF 获取位姿，不采用未经校核的里程计协方差。

新增 `nav2_odom_topic` 只选择 Nav2 的里程计话题，默认与 `odom_topic` 相同。Lite3/GO2 保持原话题；灵猫 profile 设置 `/odom_nav`，同一个 relay 在验证原始消息并发布 TF 后，将原消息以 Reliable QoS 转发，解决厂商 Best Effort 发布与 Nav2 Reliable 订阅不兼容。时间戳、frame、位姿、速度与协方差（包括原始 −1）不改动，不凭空生成可靠协方差。仅当两个话题不同才启用转发；更改自己的原始话题时一并核对 `nav2_odom_topic` 和 relay 开关。

定位模式 `RGBD/LinearUpdate`、`RGBD/AngularUpdate` 为 0，让静止机器人也执行视觉候选几何验证；建图模式仍为 0.1 m / 0.1 rad。视觉与图优化阈值不变，RTAB-Map 仍通过 TF 取位姿。

机身离地高度按用户 2026-10-14 校正后的导航站姿值 `0.36 m`（较原值下调 2 cm），可修改 `body_geometry.height` 或传 `body_height:=...`。
当前旧版里程计的 z 恒为保留零值，不拿它当作机身离地高度。
分层算法把 yaw 留在前一条边，输入中存在的 roll/pitch 留在机身边，避免重复旋转。
但当前旧版桥只提供 yaw，机身倾角无法由它恢复；这仍是名义平地/站姿模型，并非 GO2 动态高度和完整姿态的等价实测。
没有 /odom 时不发布假的位姿；缺少已配置高度时不发布假的机身高度。

每条 TF 只有一个所有者：relay 负责里程计及机身边，robot_state_publisher 负责模型、相机与 UWB 安装边。
已有外部发布者接管时，应关闭相应 `publish_odom_tf`、`publish_sensor_tf` 或模型发布，避免重复。

## 灵猫官方资料与限制

来源链：[宇泛官网产品页](https://uniubi.com/shop/buy?product=air)链接到[官方 GitHub 组织](https://github.com/uniubi-ai)，其中维护开发文档、ROS 2 bridge 和 Cyvet 模型。

| 官方来源 | 本次记录版本 | 使用的信息 |
| --- | --- | --- |
| [产品页](https://uniubi.com/shop/buy?product=air) | 2026-10-11 核对 | 站立 672×355×432 mm、趴地 718×410×178 mm，产品标称速度 0～3 m/s |
| [官方开发文档](https://github.com/uniubi-ai/uniubi-docs/tree/939d9c7286c35089c3464a2fbd04e67914b510a1) | `939d9c7286c35089c3464a2fbd04e67914b510a1` | 机体右手坐标系：X 前、Y 左、Z 上；ROS 桥接入与控制边界 |
| [官方 ROS 2](https://github.com/uniubi-ai/uniubi_ros2/tree/6e6edc057e4e232659566f0dc05e1b18393d5e1b) | `6e6edc057e4e232659566f0dc05e1b18393d5e1b` | `/odom`、`/cmd_vel`，`odom/base_link`；源码中只发布里程计消息 |
| [官方描述资产](https://github.com/uniubi-ai/uniubi_robot_description/tree/8aa1acba3cde0ec2dfc2e1dc2b4fa609a06087c9) | `8aa1acba3cde0ec2dfc2e1dc2b4fa609a06087c9` | `robots/cyvet/urdf/cyvet.urdf`、mesh；原根名称 `BASE_LINK` |

灵猫矩形轮廓是由官网整体长宽推导的 **工程初值**，并给出约 20 mm 以上的外形余量。官网尺寸没有给出所有步态、载荷和腿部摆动下的动态碰撞包络；确认实际版本及最大足端伸出范围后再调整。官网当前产品参数和描述资产也可能对应不同交付版本，以实物为准。不能把厂家最大 3 m/s 填进室内导航限速。

官方桥启动后不会自动申请控制权；`/cmd_vel` 不能代替控制权申请和进入 Walk 状态。桥、控制状态和退出释放流程应按[固定版本 ROS 2 文档](https://github.com/uniubi-ai/uniubi_ros2/blob/6e6edc057e4e232659566f0dc05e1b18393d5e1b/README.zh-CN.md)执行，本次未新增控制协议或自动申请流程。该 bridge/message/client 包属于底盘接入依赖；2026-10-11 配置时未安装，2026-10-12 已在独立 legacy 输出目录按实际 Cyvet-V1.00.000 固件完成安装和只读通信，见 [通信指南](LINGMAO_COMMUNICATION.md)。2026-10-13 已通过既有 bridge 完成 SDK 接管并进入全零速度 walking，6 个用户发送的导航目标均成功；明确的接管与释放步骤见通信指南。长期避障和地图精度仍未专项验收。

固件 `Cyvet-V1.00.002` 及以上使用官方当前 main；更早固件应选择官方 `Cyvet-V1.00.001` 标签对应的兼容接口。开发文档区分 Orin 本机接入（domain 1、`cerebellumServer`）和外部主机接入（domain 42、`robotServer`）。RK3588 作为外部主机时应按外部接入流程确认实际网络、设备 SN 和网卡。导航 launch 不改 `ROS_DOMAIN_ID`、RMW 或网卡配置。

## 每台机器首次填写相机安装外参

Lite3、GO2 的相机安装外参仍待实测。灵猫按用户明确要求先采用官方机身 STL 包围盒参考位置，后续再调：
前沿 `x_max=0.288711578 m`，上表面 `z_max=0.113681100 m`，取毫米初值。
它们是机身外形边界的组合参考点，不是对安装支架、镜头中心或 camera_link 原点的精确测量。

```yaml
body_geometry:
  height: 0.36
sensor_mount:
  parent_frame: base_link
  child_frame: camera_link
  xyz: [0.289, 0.0, 0.114]
  rpy: [0.0, 0.0, 0.0]
  calibration_status: initial_model_estimate
```

位置单位 m，角度单位 rad；初版按横向居中、水平向前处理。
站姿模型下 camera_link 的名义离地高度为 `0.36+0.114=0.474 m`。
RealSense 驱动负责 camera_link 以下的内部/光学 TF，不在机器人 URDF 中重复制作这部分。

个人可调文件已创建在 `/home/marsdog/.config/marsdog/robots/lingmao.yaml`。
修改其中 `body_geometry.height`、`sensor_mount.xyz/rpy` 后，重新启动带该 robot_config 的入口即可，无需重新编译。
若已有正确外部相机安装 TF，设置 `publish_sensor_tf:=false`。
Lite3/GO2 未提供数值时仍拒绝发布未知安装 TF。

### 灵猫 UWB 安装 TF

2026-10-14 按用户提供的安装关系加入 `uwb_mount`：相机后方 4 cm、下方 5 cm，朝向一致。这里使用 `camera_link` 的机身安装坐标轴（X 前、Y 左、Z 上），不使用光学坐标系。

~~~yaml
uwb_mount:
  parent_frame: camera_link
  child_frame: uwb_link
  xyz: [-0.04, 0.0, -0.05]
  rpy: [0.0, 0.0, 0.0]
  calibration_status: user_supplied_relative_offset
~~~

相对机身的当前位置为 `base_link→uwb_link=[0.249, 0, 0.064] m`；0.36 m 站姿下名义离地高度为 `0.424 m`。UWB 与 camera_link 的旋转一致，相机安装参数调整时会沿这条父子链同步变化。

独立 `robot_tf.launch.py` 或导航默认包含的同一入口启动时，这条固定关节由 robot_state_publisher 发布到 /tf_static；关闭模型或由外部提供相机安装 TF 时，入口自动使用独立 `robot_uwb_mount` 静态发布器。Lite3/GO2 没有提供 UWB 外参时不自动添加。

个人配置中可以直接调整 `uwb_mount.xyz/rpy`，重新启动同一入口生效，不需要重新编译。检查方式：

~~~bash
ros2 run tf2_ros tf2_echo camera_link uwb_link
ros2 run tf2_ros tf2_echo base_link uwb_link
~~~

`robot_tf.launch.py` 也发布 UWB 安装 TF；旧 `frames_only:=true` 保留兼容，它不启动 UWB 串口或运动节点。UWB 数据话题的 `sensor_frame: uwb_link` 保持不变，无线/串口延迟仍需另行标定。

2026-10-14 验证：25 项配置/TF 检查通过；隔离 Domain 86、localhost 模式下，使用合成里程计分别验证运行时 URDF 和独立静态发布器两种路径，实际 TF 偏移及旋转均符合配置。每种路径只有对应的 TF 所有者，测试进程已退出。未启动相机、UWB 硬件或实机运动。证据为 `out/rk3588-robot-profiles/uwb-mount-isolated-20261014.json`。

## URDF 与模型发布

[灵猫官方描述仓](https://github.com/uniubi-ai/uniubi_robot_description/tree/8aa1acba3cde0ec2dfc2e1dc2b4fa609a06087c9)提供 URDF 和 mesh，已通过 cyvet_description 安装。
参考 [GO2 driver.cpp](https://github.com/sun-under-bird/motion/blob/1519be2485f63e54349b85f6f766b574ea6ff700/src/go2_driver/src/driver.cpp) 的分层 TF：
base_footprint 是外部导航参考系，机身 URDF 根为 base_link，机身高度/姿态由 relay 发布，而非在 URDF 中再添加冲突的固定边。

```text
map -> odom -> base_footprint -> base_link -> camera_link -> uwb_link
                                     └-> 四腿模型
```

map→odom 由 RTAB-Map 发布；仅开模型时没有 map。
运行时将原官方机身根 `BASE_LINK` 重命名为 `base_link`，四条腿直接挂在 `base_link` 下；不再增加空的机身链接或零位移别名关节。添加相机和 UWB 固定关节，并为 12 个关节设置当前 bridge 的 JointState 名称别名。
配置中的 `description_root_frame: BASE_LINK` 用于识别官方原文件的根名称；实际发布名称由 `body_frame: base_link` 决定，不能把这个源名称也改成小写。
对应例如 FL_ABAD_JOINT→leftFrontLeg.hip、FL_HIP_JOINT→leftFrontLeg.thigh、FL_KNEE_JOINT→leftFrontLeg.calf；
四条腿均已配置，原始 URDF/mesh 文件不改动。实际关节数据已验证能生成腿部 TF，机械零点/姿态精度仍需后续实机核对。

2026-10-13 机身根统一验证：22 项配置/TF 转换检查通过，安装后的 robot_state_publisher 在隔离 ROS 域 86 中收到合成关节数据，发布 17 条模型/相机 TF，全部使用小写 `base_link` 作为机身根；测试进程已退出。这是隔离 ROS 验证，本次未启动相机或实机建图。
新启动的 `robot_tf.launch.py` 或默认包含它的 `nav.launch.py` 自动使用此配置；已经运行的模型/建图 launch 需要正常退出并重新启动，才能重新加载 robot_description。

灵猫 profile 默认启用模型和相机分支，Lite3/GO2 保持默认关闭。
模型、相机与 UWB 安装 TF 由同一 robot_state_publisher 发布，不再另启重复的静态 TF 发布器。
显式关闭模型但开启相机安装时，才使用独立静态发布器。

### 独立 TF 入口与 UWB 跟随测试

2026-10-14 已将 TF 发布启动逻辑拆分到 `robot_tf.launch.py`。UWB 跟随等测试可在一个板端终端执行：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 launch robot_slam_bringup robot_tf.launch.py \
  robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml"
~~~

独立入口负责机身模型、腿部 TF、`odom→base_footprint→base_link`、相机安装 TF、UWB 安装 TF，并保持 `/odom_nav` 的可靠转发。它不会启动相机、UWB 串口、底盘桥、RTAB-Map、Nav2、可视化或运动控制，不读取/清空地图数据库，也不解析 nav2_bringup。

相机和 UWB 固定安装 TF 不需要相机图像或关节消息即可发布；里程计及机身高度边仍需有效 `/odom`。真实腿部姿态需要桥接的 `/joint_states`。灵猫坐下时没有有效里程计，独立入口也不会伪造位姿；SDK 接管顺序见通信指南。

只查看 TF 配置、启动覆盖值和安装位置，可在上述命令后加 `print_config:=true`；它不创建 ROS 节点。机身高度、相机和 UWB 外参继续来自同一个个人 YAML。

**TF 已独立运行时，在另一个终端的原建图/导航命令中加 `start_tf:=false`**，并使用相同机器人配置和 frame/话题设置。这样导航复用已有 TF，不再启动第二份模型或 relay；重启导航也不会结束独立 TF。

没有单独启动 TF 时，原 `nav.launch.py` 命令继续可用：默认 `start_tf:=true` 会包含这个独立入口。旧 `frames_only:=true` 保留兼容，日常单独测试改用 `robot_tf.launch.py`。`map→odom` 仍由实际 RTAB-Map 建图/定位节点发布；相机内部/光学 TF 仍由 RealSense 驱动发布。

启动前检查是否已有模型/TF 发布进程，不要重复启动。结束时先停止 UWB 跟随/运动任务或导航，再按需要 Ctrl+C 关闭独立 TF 和通信桥。`out/rk3588-lingmao-urdf/frames-live.log`、`frames-launch.pid` 保留为首次模型测试的历史记录。
相机/底盘通信按各自流程启动；完整导航命令必须选择正确数据库和 localization 模式，避免重置旧图。

2026-10-14 独立 TF 拆分验证：27 项配置/TF 与启动契约检查通过；隔离 Domain 86、localhost 模式下，以合成里程计验证独立 TF、旧导航 frames_only 兼容及独立 TF 配合 start_tf=false 的实际 RTAB-Map 启动三种场景。每种场景只有一份模型发布器和里程计 relay；高度命令行覆盖、UWB 安装链与 /odom_nav 转发均验证通过。第三种场景仅使用临时数据库，未连接相机、UWB 或底盘硬件，未发布运动命令，所有测试进程已退出。证据见 `out/rk3588-robot-profiles/tf-launch-isolated-20261014.json`。

完整检查记录在 `out/rk3588-lingmao-urdf/`：
20 项无 DDS 配置/数学测试通过，三机器人安装配置检查通过，
隔离 Domain 86/loopback 的合成 Odometry/JointState 验证了完整 TF、相机位置组合及腿部 TF，
同时确认 frames_only 即使同时指定 use_nav2/use_viz/use_stereo_odometry=true 也不会启动这些节点。
实际 Domain 42 已验证相机安装静态 TF 与真实关节输入，当前坐下无 /odom，没有宣称完整导航链路实机通过。
监控增量构建 4.4 秒，两任务上限，可用内存最低约 6.53 GiB，Swap 使用零，OOM 增量零。
tools/dev.py check 本次 exit 0。

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

## 2026-10-11 初次验证范围

2026-10-11 实现时的验证记录见 `out/rk3588-robot-profiles/verification.json`，不是每次提交自动重跑的结果。包括配置/TF 转换单元测试、已安装包的三套 print-only 启动、显式参数覆盖、非法 profile 和未知外参拒绝、官方 URDF/mesh 完整性，以及隔离 DDS 域内三套 Nav2 lifecycle 服务器仅 configure 到 inactive 的验证。TF relay 使用独立域和合成 Odometry 做传输验证。

在已安装 ROS 消息和 `cyvet_description` 的板端环境中，可以对源码重复运行无 DDS 通信的配置、消息转换和描述资产测试：

```bash
source "$MARSDOG_ROOT/out/rk3588-navigation/use-navigation.sh"
PYTHONPATH="$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup:${PYTHONPATH:-}" \
  python3 -B -m unittest discover \
  -s "$MARSDOG_ROOT/robotics/ros2/src/robot_slam_bringup/test" -v
```

不启动相机、底盘桥或厂商控制客户端，不激活 Nav2、不发送导航目标，不验证实机建图、行走和避障效果。相机初版估计需继续校核；完整实机建图、定位和导航尚未验收。


## 灵猫有线通信接入

当前旧固件的官方消息、客户端和 bridge 已单独构建到 `out/rk3588-lingmao-communication-legacy`；网络配置、设备身份确认、只读 RPC/观测验证及复现命令见 [灵猫通信指南](LINGMAO_COMMUNICATION.md)。当前 Cyvet-V1.00.000 设备已使用兼容 tag 和旧版 DHCP 接入，实际只读 RPC、机器人 IMU 和电池通信通过；2026-10-13 已确认 SDK 控制状态 2、walking 和约 48～50 Hz 的 /odom，并完成 6 个实机导航目标。D435i 双目图像已完成 60 秒接收检查，相机 IMU 的 HID/IIO 支持尚未齐备，详见通信指南。
