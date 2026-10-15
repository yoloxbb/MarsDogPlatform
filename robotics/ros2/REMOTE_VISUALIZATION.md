# RK3588 板端建图、导航与电脑端远程可视化

更新日期：2026-10-14。板端为 `marsdog@192.168.5.101`，电脑使用 WSL2 Ubuntu 22.04、ROS 2 Humble。底盘桥接保留 `eth0`；相机、模型/TF 和建图通过专用环境接入 `wlan0`、`eth0`。

## 当前状态和验证边界

电脑已安装 RTAB-Map 可视化及 RViz 插件 0.23.7，与板端版本一致；两端 71 份消息和服务定义 SHA256 完全一致。灵猫模型资源已同步到电脑。

最初同时启动 RViz 和 RTAB-Map 界面，使用 Intel Arc / WSLg 的 OpenGL 4.2 硬件加速。用户报告 Windows 整机卡死并重启；系统记录意外关机事件 41、6008。原因尚未确定，启动日志不能作为图形稳定性验收结果。

初次故障后用户曾选择保持窗口关闭；随后用户自行启动 RViz。本次 Codex 没有打开或重启图形窗口，默认启动已调整为：

- 只打开 RViz；RTAB-Map 界面单独选择。
- `LIBGL_ALWAYS_SOFTWARE=true`，CPU 软件渲染；LLVM、OpenMP、OpenBLAS 各限制为 2 线程。
- RViz 10 FPS；默认关闭实时图像和完整地图点云显示。
- RTAB-Map 界面使用 `/info`、`/mapData`，不额外订阅原始双目图像。
- 应用数据使用单播；板端两块网卡都允许 SPDP 发现，并监听两块网卡的发现组播。电脑继续使用单播。

2026-10-13 已完成当前地图上的实机导航验证：用户通过 RViz 连续发送 6 个目标，均返回 `Goal succeeded`，机器人定位随任务更新；其中一次发生进度检查失败，Nav2 恢复后到达目标。结束时 SDK 为 `CONTROLLED(2)`、`walking`，速度为零。此次结果证明当前链路可以完成导航，不代替长期避障、地图精度、错误地点重定位或图形稳定性验收。

建图仍需要有效底盘里程计和完整 TF，不发布模拟位姿。

## 文件位置

| 用途 | 位置 |
| --- | --- |
| Windows 专用脚本交付 | `D:\work\scripts\ros2-remote-visualization` |
| WSL 运行副本 | `/home/chy/.local/share/marsdog/remote-visualization/tools` |
| WSL 灵猫模型资源 | `/home/chy/.local/share/marsdog/remote-visualization/description_overlay` |
| WSL 日志、PID、接收记录 | `/home/chy/.local/share/marsdog/remote-visualization/runs` |
| 板端工具源码 | `/home/marsdog/MarsDogPlatform/robotics/tools/remote_visualization` |
| 板端 DDS 配置、日志、PID | `/home/marsdog/MarsDogPlatform/out/rk3588-remote-visualization` |

2026-10-13 已将板端 `~/.bashrc` 的自动加载入口改为 `use-remote-board.sh`。新交互式终端自动使用统一 ROS Domain 42 双网卡环境；已有终端执行 `source ~/.bashrc`。原 `start-lingmao-bridge.sh` 内部仍可加载 Ethernet 专用 SDK 环境，两者已经验证互通。自动加载环境不等于自动启动通信、相机或建图进程。

电脑脚本使用 `ROS_DOMAIN_ID=42`、`rmw_cyclonedds_cpp`，自动发现已配对板端并按实际路由选择网卡。当前地址 `192.168.5.101`、`192.168.5.99` 仅为本次现场地址，日常启动不再绑定它们。

## 本机 WSL 启动 RViz 与 RTAB-Map 界面

先按下文启动板端通信、相机，以及建图或导航，并保持三个板端终端运行。电脑侧只运行可视化，不启动另一套建图或 TF 发布节点。用户现已确认接通可用；下面由用户手动执行。

### 1. Windows 打开 WSL

在 Windows PowerShell 或 Windows Terminal 的 PowerShell 标签页执行：

~~~powershell
wsl -d Ubuntu-22.04
~~~

进入后是本机 Ubuntu 的终端（当前用户 `chy`），不是 `marsdog@lubancat` 的板端 SSH 终端。以下命令在这个 WSL 终端执行。

### 2. WSL 启动 RViz2

~~~bash
bash "$HOME/.local/share/marsdog/remote-visualization/tools/start-remote-viz.sh" \
  use_rviz:=true use_rtabmap_viz:=false
~~~

启动脚本自动发现已配对板端的当前 IP，检查专用防火墙规则，加载 ROS Humble、Domain 42、Cyclone DDS、单播 Peer 和灵猫模型资源，并启用 CPU 软件渲染及线程限制；无需手工填写 IP 或另外加载 ROS 环境。

RViz 默认 `Fixed Frame=map`。地图已有输出时保持 `map`，通过 `/map` 查看栅格地图；模型来自 `/robot_description`，位置来自 TF。尚未产生 `map→odom` 时，可暂用 `base_link` 查看模型。图像和完整地图点云先保持关闭，单窗口稳定后再逐项启用。

### 3. WSL 切换为 RTAB-Map 界面

先在启动 RViz 的 WSL 终端按 Ctrl+C，等待 RViz 和 launch 退出，再执行：

~~~bash
bash "$HOME/.local/share/marsdog/remote-visualization/tools/start-remote-viz.sh" \
  use_rviz:=false use_rtabmap_viz:=true
~~~

该界面订阅板端 `/info`、`/mapData`，不额外订阅原始双目图像。之前双窗口 GPU 使用后发生 Windows 整机卡死，原因未确定；当前先一次只开启一个窗口。软件渲染已配置，但图形长期稳定性尚未验收。

### 4. WSL 检查是否收到板端话题

另开一个 WSL 终端执行：

~~~bash
source "$HOME/.local/share/marsdog/remote-visualization/tools/use-remote-viz.sh"
ros2 topic list --no-daemon
timeout 10s ros2 topic echo /info --no-daemon --once
~~~

应能发现 `/map`、`/info`、`/mapData`、`/tf`、`/tf_static` 等话题。仅发现名称不代表有地图；本次已经实际收到栅格数据和完整 TF。如果终端提示可视化已运行，先关闭原启动终端中的程序，不重复启动第二份。

### 5. 正常退出

在启动界面的 WSL 终端按 Ctrl+C，等待 launch 及其子进程退出。退出电脑可视化不会关闭板端建图或导航；全部结束时按下文顺序关闭板端 C、相机和通信桥，让建图数据库正常保存。

### 可选：PowerShell 直接调用 WSL 入口

也可以不手动进入 WSL，在 Windows PowerShell 执行同一套单窗口配置：

~~~powershell
& 'D:\work\scripts\ros2-remote-visualization\start-remote-viz.ps1'
~~~

切换为 RTAB-Map 界面时，先退出已有窗口，再执行：

~~~powershell
& 'D:\work\scripts\ros2-remote-visualization\start-remote-viz.ps1' 'use_rviz:=false' 'use_rtabmap_viz:=true'
~~~

两种入口是同一套配置，选择一种即可。板端环境入口不得加载到电脑 WSL 中；电脑使用 `use-remote-viz.sh`，板端使用 `use-remote-board.sh`。

## 从零启动当前灵猫双目建图

以下复现针对已经准备好依赖的当前板端，板端 IP 为 `192.168.5.101`。灵猫通电、有线接入 `eth0`，D435i 接入板端 USB。打开三个板端 SSH 终端，按顺序启动；命令均在前台运行，保留各终端便于停止。通信桥只连接设备；启动后在查询终端明确调用下方全零速度 walking 接管步骤。

| 顺序 | 终端 | 启动内容 |
| --- | --- | --- |
| 1 | 板端 A | 灵猫通信桥，将机器人数据发布为 `/odom`、`/joint_states` 等 ROS 2 话题 |
| 1a | 板端查询终端 | App 释放控制权后，调用全零速度 walking；核对 SDK 控制权和有效里程计 |
| 2 | 板端 B | D435i 双目红外图像、CameraInfo、相机内部 TF |
| 3 | 板端 C | `nav.launch.py`：模型、里程计 TF 转发和 RTAB-Map 建图 |
| 可选 | 本机 WSL / Windows PowerShell | 用户手动开启单个电脑可视化窗口 |

### 板端 A：启动灵猫通信

~~~bash
ros2 daemon stop
bash "$HOME/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/start-lingmao-bridge.sh"
~~~

已有 `robot.env` 提供本机设备 ID，不需在命令中另填 SN。通信桥使用 `eth0`，`ROS_DOMAIN_ID=42`。`ros2 daemon stop` 只停止 ROS CLI 查询守护进程，使后续查询不沿用旧 DDS 配置，不会停止通信桥、相机或建图节点。

之前相机、建图和通信桥已按测试清理要求关闭，`.bashrc` 只加载环境，不会自动启动这些节点。仅加载环境不能恢复 `/odom`。

### 板端查询终端：SDK 接管并恢复里程计

通信桥启动后，先在手机 App 释放控制权，并确认当前没有执行中的导航目标。释放后趴下、`/odom` 暂停是本次旧固件的实际表现；不要只靠 App 站立后直接启动导航。

在另一个板端终端执行一次：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 service call /motion/start_action uniubi_motion_bridge/srv/StartMotionAction \
  '{action: walking, params_json: "{\"lineVelocityX\":0.0,\"lineVelocityY\":0.0,\"velocity\":0.0}"}'
timeout 10s ros2 topic echo /motion/status --no-daemon --once
timeout 10s ros2 topic echo /odom --no-daemon --once --qos-reliability best_effort
~~~

这个服务通过已运行的 bridge 申请 SDK 控制权，并进入全零速度 `walking`。确认服务 `success: true`、`control_state: 2`、`current_action: walking`，且收到有效里程计后，再继续启动相机和建图/导航。通信桥重启或控制权再次切换后，重新检查并执行此步骤；每次开查询终端不需要重复调用。

[官方高级控制说明](https://github.com/uniubi-ai/uniubi-docs/blob/main/README.zh-CN.md#安全说明)要求先进入全零速度 walking，再执行其他受状态机约束的非趴下动作。本设备先调用 `standing` 曾返回 `kActionRejected(8)`；当前已按正确顺序完成接管。环境脚本和 `.bashrc` 只加载配置，不自动申请控制权或执行动作。

### 板端 B：启动 D435i

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 launch realsense2_camera rs_launch.py \
  enable_infra1:=true enable_infra2:=true \
  depth_module.infra_profile:=640,480,15 \
  enable_color:=false enable_depth:=false \
  enable_gyro:=false enable_accel:=false \
  enable_sync:=true
~~~

当前 `nav.launch.py` 使用双目红外图像计算立体深度，因此本流程只需要左右红外流；RGB、硬件深度和 IMU 均关闭。建图的深度距离限制仍由 RTAB-Map 参数控制。若另有程序使用 RGB/深度，可按该程序要求单独调整相机流。

### 板端 C：启动模型、TF 和建图

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
mkdir -p "$HOME/.ros"
map_db="$HOME/.ros/rtabmap_lingmao_$(date +%Y%m%d_%H%M%S).db"
printf '本次地图数据库：%s\n' "$map_db"
ros2 launch robot_slam_bringup nav.launch.py \
  robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml" \
  frames_only:=false localization:=false \
  use_nav2:=false use_viz:=false use_stereo_odometry:=false \
  database_path:="$map_db"
~~~

这个入口默认包含独立 `robot_tf.launch.py`，启动 `robot_state_publisher`、`odometry_tf_relay`，随后启动 RTAB-Map。若已经单独启动 robot_tf.launch.py，在本命令中加 `start_tf:=false`，复用已有 TF。当前配置使用灵猫里程计，通过 TF 读取位姿；OpenVINS 和双目 VO 均不需要启动。Nav2 与板端图形界面关闭。

建图模式包含 `-d`，会清空指定数据库，因此上述命令每次生成新的数据库名称。结束前记下终端打印的数据库路径；已有地图不得直接用这条建图命令打开，重定位使用 `localization:=true` 并指定已有数据库。

当前机身高度按用户 2026-10-14 校正改为 0.36 m（下调 2 cm），相机挂载为模型估算初版 `[0.289, 0, 0.114]`、水平朝前，尚未完成实测外参标定。

### 板端 D：检查输入和 TF

另开一个查询终端：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 topic list --no-daemon
timeout 10s ros2 topic echo /odom --no-daemon --once --qos-reliability best_effort
~~~

应能发现 `/odom`、`/joint_states`、左右红外图像与 CameraInfo、`/tf`、`/tf_static`。RTAB-Map 节点启动后还应出现 `/info`、`/mapData` 等话题；发现话题不代表已产生有效地图。

本设备坐下或释放控制权后 `/odom` 可能暂停。按前面的 SDK 接管步骤进入全零速度 walking 后，本次实际收到约 48～50 Hz 的里程计。仅话题名称存在不能证明里程计可用；没有有效里程计时，relay 不会伪造位姿，建图也无法正常更新。

逐条检查 TF，看到结果后分别按 Ctrl+C：

~~~bash
ros2 run tf2_ros tf2_echo odom base_footprint
ros2 run tf2_ros tf2_echo base_footprint camera_infra1_optical_frame
~~~

链路应为 `odom → base_footprint → base_link → camera_link → 相机内部坐标系`；相机还有 `camera_link → uwb_link` 固定分支，偏移 `[-0.04, 0, -0.05] m`、相对旋转为零，由模型发布器负责。`map → odom` 由 RTAB-Map 在获得有效输入后发布。当前旧版里程计只有 yaw，无法恢复真实机身 roll/pitch。

如果 `ros2 topic list` 只显示 `/parameter_events`、`/rosout`，先确认 A/B/C 终端中的进程未退出，再使用本节的 `--no-daemon` 查询。日志提示 `wlan0` 不支持组播时，应结合配置判断：当前修复配置使用 SPDP 发现、单播应用数据；若再次出现这条提示，应核对是否仍载入旧 XML，或接口是否被标记为不支持组播。

### 可选电脑显示与结束清理

电脑显示命令见上面的“本机 WSL 启动 RViz 与 RTAB-Map 界面”。用户可按自己的需要手动查看单个窗口；上述板端流程可独立建图。下面的 DDS 修复验证已确认实际建图输出及电脑接收，但没有验收图形长期稳定性或地图精度。

自己启动复现后，先取消正在执行的导航目标，再在板端 C（建图/导航）按 Ctrl+C，等待数据库保存及子进程退出。若本次也结束 SDK 控制，在通信桥仍运行时，于查询终端执行：

~~~bash
ros2 service call /motion/release_control std_srvs/srv/Trigger '{}'
~~~

本次旧固件释放 SDK 控制后会趴下，里程计可能暂停；因此不要在导航仍运行时释放。然后按需要关闭电脑可视化、B（相机）、A（通信），并关闭查询终端内的 echo/hz/tf2_echo。只切换建图/定位模式时保留 A/B 和 SDK 控制，不执行释放。不要直接关掉 SSH 窗口替代正常退出。

确认没有本次留下的进程：

~~~bash
pgrep -af 'motion_bridge.launch.py|uniubi_motion_bridge_node|rs_launch.py|realsense2_camera_node|component_container|nav.launch.py|robot_state_publisher|odometry_tf_relay|rtabmap_slam/rtabmap'
~~~

无输出表示上述进程已退出；有输出时先核对 PID 与本次终端，勿使用 `pkill` 或 `killall` 停止其他用户的程序。原有 DHCP、网络配置等常驻服务不属于测试清理范围。

## 单独 TF 用于 UWB 等测试

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 launch robot_slam_bringup robot_tf.launch.py \
  robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml"
~~~

此入口只启动模型、里程计 relay 和安装 TF，不启动相机、建图、Nav2、UWB 串口或运动控制。固定安装边立即发布；odom 相关边仍需要通信桥提供有效里程计。若后续建图/导航与这个 TF 终端同时运行，在原 nav.launch.py 命令中加 `start_tf:=false`；机器人配置和 frame/话题覆盖应保持一致。map→odom 仍由 RTAB-Map 发布。

## 使用已有地图启动灵猫定位与导航

前面的命令是“只建图”。导航仍使用同一个 `nav.launch.py`，但改成 `localization:=true use_nav2:=true`，并加载已经保存的地图数据库。

| 用途 | localization | use_nav2 | 数据库 |
| --- | --- | --- | --- |
| 建新图 | false | false | 新文件；该模式带 `-d`，重置指定数据库 |
| 仅使用已有地图定位 | true | false | 已保存的地图 |
| 使用已有地图定位并导航 | true | true | 已保存的地图 |

### 1. 结束建图，保留通信和相机

在板端 C 的建图终端按 Ctrl+C，等待 RTAB-Map 和该 launch 的子进程退出、数据库保存完成。板端 A（通信）和 B（相机）保持运行，使用上文同一套启动命令即可；不要同时运行两份 `nav.launch.py`。

从零启动导航时，先启动 A、在查询终端完成全零速度 walking 接管，再启动 B，最后把 C 的建图命令替换为下面的导航命令。底盘必须提供有效 `/odom`，并确认 `control_state=2`、`current_action=walking`。

### 2. 板端 C：加载已保存地图并启动 Nav2

先查看已有数据库：

~~~bash
ls -lh "$HOME"/.ros/rtabmap_lingmao_*.db
~~~

下面用板端当前已有的 `rtabmap_lingmao_20261013_152245.db` 举例。**请把 `map_db` 替换为本次建图终端打印并正常保存的真实路径**；导航不再用 `date` 生成新的空数据库。

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
map_db="$HOME/.ros/rtabmap_lingmao_20261013_152245.db"

if [ ! -s "$map_db" ]; then
  printf '地图数据库不存在或为空：%s\n' "$map_db"
else
  ros2 launch robot_slam_bringup nav.launch.py \
    robot:=lingmao \
    robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml" \
    frames_only:=false localization:=true \
    use_nav2:=true use_viz:=false use_stereo_odometry:=false \
    database_path:="$map_db"
fi
~~~

此命令在板端启动模型、里程计 TF relay、RTAB-Map 重定位与 Nav2 导航栈。定位模式不传 `-d`，当前配置将已有数据库设为只读；RTAB-Map 从数据库提供 `/map`，普通导航不需要另外启动 map_server 或把地图另存成 YAML。相机仍提供双目实时观测，Nav2 的 STVL 使用 RTAB-Map 的 `/local_grid_obstacle` 与 `/local_grid_ground`。

里程计继续通过 TF 提供 RTAB-Map 位姿，未改用不可靠的消息协方差。灵猫原始 `/odom` 是 Best Effort；同一个 `odometry_tf_relay` 在验证输入并发布 TF 后，将原消息转发到 Reliable 的 `/odom_nav`，Nav2 的 controller_server 和 bt_navigator 订阅该话题。时间戳、位姿、速度、frame 和原始协方差均保留，原始 `/odom` 及厂商 bridge 不改动。

定位模式单独设置 `RGBD/LinearUpdate=0`、`RGBD/AngularUpdate=0`，让机器人静止时也能按现有 1 Hz 处理频率验证视觉重定位候选。建图仍使用 0.1 m / 0.1 rad；20 内点、2 像素重投影等几何阈值保持不变。本次静止定位已接受候选 81/82，内点 36～47。只读定位下 `Loop/Last_id` 为 0 不等于重定位失败，应结合 `/info` 的 accepted_hypothesis_id、几何统计和实际地图位姿判断。

板端 `use_viz:=false` 保留，电脑使用下文 WSL 单窗口入口。该 launch 不申请运动控制权；实际行走前完成上方明确的 SDK 接管步骤。

### 3. 核对导航状态

在另一个板端查询终端执行：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 action list -t
ros2 lifecycle get /bt_navigator
ros2 lifecycle get /controller_server
timeout 8s ros2 run tf2_ros tf2_echo map base_footprint
~~~

应有 `/navigate_to_pose [nav2_msgs/action/NavigateToPose]`，`bt_navigator` 和 `controller_server` 应为 `active`，TF 可查询。`timeout` 到时自动结束 TF 查询属于正常行为。先在 RViz 确认地图与机器人的实际位置一致，再发送导航目标；仅有 `map→odom` 不能证明已经正确重定位。

需要检查实时障碍输入时，在查询终端执行 `ros2 topic hz /local_grid_obstacle`，观察收到的频率后按 Ctrl+C。没有新鲜图像、有效里程计、正确定位或障碍观测时，先解决输入问题。

### 4. WSL：显示地图并指定导航目标

启动 RViz 的命令与建图时相同，在本机 WSL 执行：

~~~bash
bash "$HOME/.local/share/marsdog/remote-visualization/tools/start-remote-viz.sh" \
  use_rviz:=true use_rtabmap_viz:=false
~~~

保持 `Fixed Frame=map`。已配置 **Navigation 2** 面板、**Nav2 Goal** 工具及 **2D Pose Estimate** 工具，无需自行添加目标发布插件。Nav2 Goal 在地图上按下并拖动设置目标位置和朝向，通过 Navigation 2 面板向 `/navigate_to_pose` action 提交目标；面板显示导航状态并可取消当前任务。2D Pose Estimate 发布 `/initialpose`，用于人工提供地图中的定位初值，不能代替视觉重定位验收。

| RViz 项目 | 话题或接口 | 默认状态 |
| --- | --- | --- |
| Map：已有地图 | `/map` | 开启，接收缓存地图 |
| Global Costmap：全局代价地图 | `/global_costmap/costmap` | 开启 |
| Local Costmap：局部代价地图 | `/local_costmap/costmap` | 开启 |
| Global Plan：全局规划 | `/plan` | 开启 |
| Smoothed Plan：平滑后路径 | `/plan_smoothed` | 开启 |
| Controller Reference Path：控制器参考路径 | `/transformed_global_plan` | 开启；不是 MPPI 全部预测轨迹 |
| Robot Footprint：机器人轮廓 | `/local_costmap/published_footprint` | 开启 |
| Navigation 2 / Nav2 Goal | `/navigate_to_pose` | 已配置 |
| 2D Pose Estimate | `/initialpose` | 已配置，需手动操作 |

发送目标前，路径显示没有数据属于正常情况。图像和完整点云仍保持关闭，10 FPS、CPU 软件渲染和线程限制继续生效。RTAB-Map 界面用于观察地图与重定位，Nav2 目标通过 RViz 设置。

RViz 默认文件为 `/home/chy/.local/share/marsdog/remote-visualization/tools/remote_viz.rviz`。更新后，已运行的 RViz 使用 **File → Open Config** 重新打开该文件，或正常退出后按上述 WSL 命令启动。

导航结束时先在 Navigation 2 面板取消当前目标，再正常退出板端 C（导航）。需要结束底盘控制时，按上文顺序在 bridge 仍运行时释放 SDK，然后按需要退出电脑 RViz、相机 B 和通信 A。保留通信、相机用于下一次操作时，只退出 C 和本次查询程序。

本节已按板端实际 `nav.launch.py` 与 Nav2 源码核对。2026-10-13 用户已重启导航、重载 RViz 配置并自行发送 6 个目标，6 个 action 均以状态 4（Succeeded）结束。Codex 只读观察用户导航；另行调用的 ComputePathToPose 仅验证规划，返回 46 个路径点且未产生速度消息。Codex 未打开图形窗口。一次目标发生进度检查恢复后成功，长期避障及相机外参精度仍待后续评估。

本次 22 项配置/TF 测试、隔离 Domain 86 的真实 ROS QoS 转发测试、`python3 -B tools/dev.py check` 均通过；Python 启动包以两任务监控增量安装。实机结果保存在 `out/rk3588-remote-visualization/navigation-readiness-result-2026-10-13.json`。临时诊断节点均已退出，用户自己启动的通信、相机、导航和 RViz 保留。

## 地图已加载但 RViz 或 Nav2 收不到

2026-10-13 已确认：RTAB-Map 的 `/map` 使用 `Reliable + Transient Local` 保留最后一次地图。定位时地图可能不再变化；旧 RViz 的 `Volatile` 订阅与旧 Nav2 静态层普通订阅会错过启动时发布的缓存地图。

当前修复：

- RViz 的 Map、Global Costmap、Local Costmap 均使用 `Reliable + Transient Local`。
- 板端 `config/nav.yaml` 的 `global_costmap.global_costmap.ros__parameters.static_layer.map_subscribe_transient_local` 已设为 `True`。
- Nav2 此参数只在静态层初始化时读取，修改后需正常退出并重新启动导航。相机与通信桥可继续运行。
- RViz 重载配置后可订阅已有缓存地图，无需重建数据库或反复发送目标来刷新地图。

用户重启导航并重载 RViz 后，板端和电脑 WSL 都实际收到 `/map`（645×441）、全局代价地图（645×441）及局部代价地图（120×120），分辨率均为 0.05 m。RViz 与 Nav2 静态层的实际地图订阅为 `Transient Local`，`bt_navigator`、`controller_server`、`planner_server` 均为 `active`。上述尺寸是地图消息接收和节点状态的验证。随后完成了本指南所述静止重定位与 6 个实机导航目标；地图精度和错误地点重定位仍未专项验收。

## 目标已下发但灵猫不走

当前速度链路为：

~~~text
controller_server → /cmd_vel_nav → velocity_smoother → /cmd_vel → uniubi_motion_bridge → 灵猫 SDK
~~~

通信桥已订阅 `/cmd_vel`，不需要另加速度转发程序。启动桥接和导航，不等于 SDK 已获得运动控制权。

只读检查：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 topic info /cmd_vel -v
timeout 10s ros2 topic echo /motion/status --no-daemon --once
~~~

`control_state=0` 表示未连接，`1` 表示已连接，`2` 表示 SDK 已获得控制权。SDK 的 `setActionParams` 没有控制权时直接拒绝；仅在 App 里站立并有 `/odom` 数据，仍不足以执行 Nav2 速度。实际使用按上方明确的服务调用获取控制权并进入全零速度 walking；环境、可视化和导航 launch 入口本身不会自动申请控制权。

需区分没有 `/cmd_vel_nav`、没有最终 `/cmd_vel`、SDK 拒绝速度、底盘执行后未位移。故障发生时桥接为 `CONNECTED(1)`、`current_action` 为空，旧目标还出现无有效路径和 `Failed to make progress`。现已修复 SDK 接管、Nav2 里程计 QoS 和静止视觉重定位，6 个新目标均成功。应分别处理控制状态、定位/规划与 TF，不能只凭目标点已显示判断底盘已收到可执行指令。

## 通信维护

Windows 与 WSL Hyper-V 已配置专用 UDP 入站规则：只允许 `192.168.5.101`；端口 `17900–17971` 用于 domain 42，`28900–28971` 用于隔离验证 domain 86。没有关闭系统防火墙或放开全部 WSL 入站流量。

重新应用时，在管理员 PowerShell 执行：

```powershell
& 'D:\work\scripts\ros2-remote-visualization\configure-windows-firewall.ps1' -BoardIP '192.168.5.101'
```

板端环境入口每次加载时自动重新生成 DDS 配置；排障时也可单独执行：

```bash
python3 "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/configure-dds.py" \
  --role board \
  --output "$HOME/MarsDogPlatform/out/rk3588-remote-visualization/cyclonedds-board.xml"
```

运行中的 ROS 进程保留原 DDS 环境，变更后需重启相应进程。电脑每次按当前路由生成 XML。WSL 接收上限为 8 MiB，文件为 `/etc/sysctl.d/99-marsdog-remote-viz-udp.conf`；上限不会提前为每个未使用的 socket 分配内存。

电脑依赖通过 apt 安装，既有 ROS 包未升级：`ros-humble-rtabmap-viz`、`ros-humble-rtabmap-rviz-plugins` 和 0.23.7 配套依赖。重新安装前确认与板端消息定义匹配。模型资源是描述包资产，没有复制板端 ARM64 可执行程序到电脑。

参考：[WSLg 图形应用](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)、[WSL 镜像网络](https://learn.microsoft.com/en-us/windows/wsl/networking)、[Mesa 软件渲染](https://docs.mesa3d.org/envvars.html)。

## 自动适配 IP 与切换 Wi-Fi

当前已经安装自动发现和配置刷新。换 Wi-Fi 后，不需要手工填写板端 IP、电脑 IP 或修改 XML，继续使用上面的 WSL/PowerShell 启动命令即可。

### 自动处理的内容

- 板端 `.bashrc` 加载 `use-remote-board.sh` 时，自动读取当前默认路由和有效 IPv4 接口，重新生成 DDS 的本机 Peer；不再绑定电脑 `192.168.5.99`。
- 板端现有系统 Avahi 服务发布专用 DNS-SD 标识 `MarsDog-RK3588-88b1eec592f5`，类型为 `_marsdog-ros2._tcp`。服务随网络地址变化发布当前地址，已设置开机启用。
- Windows/WSL 启动入口查找这台已配对板子，校验固定的 SSH 主机密钥，并通过 Windows 已配置的免密 SSH 只执行 `true`。不用依赖可能同名的 `lubancat.local`。
- 电脑自动按当前到板端的路由选择网卡，生成单播 DDS XML。
- 自动检查 Windows 和 WSL Hyper-V 的原有受限防火墙规则。板端 IP 改变时，只把这两条规则更新为已验证的新板端 IP，不开放全部来源。更新需要管理员权限时，Windows 会弹 UAC 授权窗口；无需手工输入新 IP。

电脑和板端需要在可互通的局域网中，网络允许 mDNS（UDP 5353）发现。当前灵猫有线网为 `192.168.50.0/24`；新 Wi-Fi 不应与它使用同一个网段。更换板端系统或 SSH 主机密钥后需要重新配对；同一板端系统仅换 Wi-Fi 不需要配对。

依据：[mDNS（RFC 6762）](https://www.rfc-editor.org/rfc/rfc6762.html)、[DNS-SD（RFC 6763）](https://www.rfc-editor.org/rfc/rfc6763.html)。DDS 通过电脑主动联系板端学习对方地址，板端无需固定电脑 IP，见 [Cyclone DDS 发现说明](https://cyclonedds.io/docs/cyclonedds/0.10.5/config/cyclonedds_specifics.html#asymmetrical-discovery)。

### 日常换 Wi-Fi 后的顺序

1. 电脑和板端连接新的可互通 Wi-Fi。
2. 正常退出旧的电脑可视化、板端建图和相机，让数据库保存。
3. 新开板端 SSH 终端，或在已有终端执行 `source ~/.bashrc`。按照上文完整步骤重新启动相机以及建图或导航；通信桥的 Ethernet 配置仍然有效。
4. 按原 WSL 命令启动一个可视化窗口，无需 `export MARSDOG_BOARD_IP`。若弹 Windows UAC 提示，确认更新专用防火墙规则。

这是“启动时自动发现和刷新”，正在运行的 DDS 节点不会在另一个终端 `source` 后立即迁移到新地址；切换网络后需要重新启动相关 ROS 进程。建图模式会清空指定数据库，重新建图使用新文件名；使用已有地图时选择重定位模式，勿用 `-d` 清空已有数据。

### 只准备网络，不打开图形窗口

Windows PowerShell：

~~~powershell
& 'D:\work\scripts\ros2-remote-visualization\start-remote-viz.ps1' -PrepareOnly
~~~

或在 WSL：

~~~bash
bash "$HOME/.local/share/marsdog/remote-visualization/tools/start-remote-viz.sh" --prepare-only
~~~

成功时打印自动发现的板端地址、Domain 42 和 DDS 文件位置。以上命令不启动 RViz、RTAB-Map 界面或另一套建图。

强制重新发现（不使用上次地址缓存、不修改防火墙）：

~~~powershell
& 'D:\work\scripts\ros2-remote-visualization\prepare-remote-network.ps1' -ForceDiscovery -DiscoverOnly
~~~

### 专用脚本、配对文件及一次性安装

| 文件 | 用途 |
| --- | --- |
| `network-discovery.ps1` | 有边界的 DNS-SD 解析与板端 SSH 密钥验证 |
| `prepare-remote-network.ps1` | 自动找板端并检查/更新专用防火墙规则 |
| `board-identity.json` | 当前板端的公共主机密钥和发现标识，不含私钥 |
| `board-discovery.service` | 当前板端的 Avahi 发布配置 |
| `install-board-discovery.sh` | 安装发布配置到已有系统 Avahi，保留原有服务 |
| `test/` | 不连接硬件的网络变化和 DNS 解析回归 |

上述文件与原有启动、DDS、可视化、防火墙脚本一并保存在 `D:\work\scripts\ros2-remote-visualization`；WSL 副本在 `~/.local/share/marsdog/remote-visualization/tools`。不要只复制启动入口。

板端通用工具源码在 `robotics/tools/remote_visualization`；设备配对文件保存在 `out/rk3588-remote-visualization`。2026-10-13 用户已执行一次性安装，不用每次重复执行：

~~~bash
sudo bash "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/install-board-discovery.sh" \
  "$HOME/MarsDogPlatform/out/rk3588-remote-visualization/board-discovery.service"
~~~

系统发布文件为 `/etc/avahi/services/marsdog-rk3588.service`。Windows 网络缓存及每次发现后的防火墙状态在 `%LOCALAPPDATA%\MarsDog\remote-visualization`。新电脑需要先具备到已配对板端的 Windows 免密 SSH，再复制完整专用脚本和配对文件。

### 本次验证与边界

- 系统 Avahi 服务已确认 `active`、`enabled`，系统发布文件内容正确；停止临时发布器后，强制 DNS-SD 发现仍能找到正确板端并通过 SSH 密钥校验。
- 两个无图形的启动入口（PowerShell `-PrepareOnly`、WSL `--prepare-only`）均通过。
- 隔离 ROS Domain 86 双向通信通过，板端收到 95 条、电脑收到 94 条；板端 DDS 不含固定电脑 Peer。
- 4 项离线网络变化用例覆盖新网段、新默认网卡、Ethernet 单独启动和发现组播；6 项离线 DNS 解析/身份用例覆盖正常数据、错误身份、错误服务、查询包、截断包、指针循环，全部通过。
- `python3 -B tools/dev.py check` 通过。测试程序使用隔离域，未向机器人发送运动命令；临时发布器和测试节点均已退出。
- 未实际切换现场 Wi-Fi或重启板子；新网段由离线用例验证。没有重新打开图形窗口或验收图形长期稳定性。

当前读写内存缓冲、DDS 报文大小、Domain 42、底盘协议及 TF/里程计策略保持原值。原始自动适配检查记录在 Windows `D:\work\资料归档\硬件验证\远程可视化\2026-10-13\auto-network-result-2026-10-13.json`。

## 2026-10-13 首次双网卡接通记录（自动 IP 改造前）

本节保留首次接通时的固定地址及实机建图结果；当前配置以“自动适配 IP”一节为准，板端已经移除固定电脑 Peer。

旧配置将 `wlan0` 标记为 `multicast=false`，同时保留全局组播。Cyclone DDS 0.10.5 在任一选中接口不支持组播时会关闭整个进程的组播，造成板端建图环境发现不了 Ethernet 通信桥。旧配置下 Ethernet 环境有约 49 Hz `/odom`，建图环境没有收到该输入。

首次修复采用下列配置；当前自动版本不再含固定电脑 Peer：

- `wlan0`、`eth0` 均标记为支持组播。
- `AllowMulticast=spdp`：只用组播进行参与者发现，应用数据采用单播。
- `MulticastRecvNetworkInterfaceAddresses=all`：监听两块网卡上的发现组播。
- Peer 包含电脑 `192.168.5.99` 和两块本机接口地址 `192.168.5.101`、`192.168.50.1`。
- 保留 `MaxMessageSize=1200B`、`FragmentSize=1000B`、Domain 42 和既有缓冲上限。

依据：[Cyclone DDS 0.10.5 初始化源码](https://github.com/eclipse-cyclonedds/cyclonedds/blob/0.10.5/src/core/ddsi/src/q_init.c#L1310)。原 XML、生成器、环境入口和 `.bashrc` 已备份至板端 `out/rk3588-remote-visualization/backups/dds-connect-20261013-115120`。

用户重新启动正式会话后，本次只读采样 12 秒：`/odom` 571 条、`/joint_states` 589 条；双目图像 176/180 帧；`/info` 和 `/mapData` 各 12 条。已收到 `odom→base_footprint→base_link→camera_link→camera_infra1_optical_frame` 完整链，机身高度为 0.38 m；`map→odom` 正常发布。

电脑 WSL 随后只读采样 8 秒：收到地图 4 条、`/info` 7 条、TF/静态 TF 合计 475 条。最新地图为 241×171 栅格、分辨率 0.05 m，已知栅格 13806 个。已确认建图在产出有效地图且电脑能接收；尚未验证地图精度、回环正确率、重定位、Nav2 实机导航和软件渲染长期稳定性。

架构及平台检查 `python3 -B tools/dev.py check` 通过。所有 Codex 本次只读检查进程已正常退出；用户自行启动的通信、相机、建图和 RViz 继续运行。本次没有发送运动命令，没有切换为话题协方差输入。

原始记录在板端 `out/rk3588-remote-visualization/dds-connect-readonly-check-2026-10-13.json`，电脑记录在 WSL `~/.local/share/marsdog/remote-visualization/runs/dds-connect-pc-map-check-2026-10-13.json`。Windows 副本位于 `D:\work\资料归档\硬件验证\远程可视化\2026-10-13`。

## 首次故障后后台接收结果（历史）

窗口保持关闭后，电脑端实际订阅 15 秒：左图 35 帧、右图 28 帧，均为 640×480 mono8、每帧 307200 字节；接收约 2.37/1.88 FPS。收到模型描述 1 条及静态模型 TF 1 条，WSL 可用内存最低约 14.24 GiB。本次没有验证完整地图、动态 odom TF 或图形稳定性。

本轮最初只关闭了诊断相机和建图，清理不完整。2026-10-13 已补充关闭本次测试启动的模型/TF 和通信桥，并核对相机、建图、robot_state_publisher、里程计 TF 转发器和通信桥均无残留进程。电脑可视化窗口继续保持关闭。测试结束后必须关闭本次测试启动的进程及其子进程，并确认退出；只有用户明确要求时才保留后台测试进程。

## 重新准备电脑依赖和模型

已有 Ubuntu 22.04 / ROS Humble 时，安装匹配版本：

```bash
sudo apt-get install --no-install-recommends \
  ros-humble-rviz2 ros-humble-rmw-cyclonedds-cpp \
  ros-humble-rtabmap-viz=0.23.7-1jammy.20260908.074021 \
  ros-humble-rtabmap-rviz-plugins=0.23.7-1jammy.20260908.071032
```

板端生成描述资源与 ament 标记归档：

```bash
mkdir -p "$HOME/MarsDogPlatform/out/rk3588-remote-visualization"
tar -C "$HOME/MarsDogPlatform/out/rk3588-navigation/install/cyvet_description" \
  -czf "$HOME/MarsDogPlatform/out/rk3588-remote-visualization/cyvet-description-share.tar.gz" \
  share/cyvet_description share/ament_index/resource_index/packages/cyvet_description
```

Windows PowerShell 复制至临时目录，再解包到 WSL：

```powershell
$temporaryArchive = Join-Path $env:TEMP 'cyvet-description-share.tar.gz'
scp marsdog@192.168.5.101:/home/marsdog/MarsDogPlatform/out/rk3588-remote-visualization/cyvet-description-share.tar.gz $temporaryArchive
$archiveInWsl = (& wsl -d Ubuntu-22.04 -- wslpath -a -u $temporaryArchive).Trim()
$wslHome = (& wsl -d Ubuntu-22.04 -- printenv HOME).Trim()
& wsl -d Ubuntu-22.04 -- mkdir -p "$wslHome/.local/share/marsdog/remote-visualization/description_overlay"
& wsl -d Ubuntu-22.04 -- tar -xf $archiveInWsl -C "$wslHome/.local/share/marsdog/remote-visualization/description_overlay"
```

Windows 入口直接读取 `D:\work\scripts\ros2-remote-visualization` 的完整配置；WSL 运行副本更新时同步相应文件。模型是数据资产，不复制 ARM64 库或程序到 x86_64 电脑。
