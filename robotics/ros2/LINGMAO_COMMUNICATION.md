# RK3588 灵猫有线通信与 ROS 2 接入

更新日期：2026-10-14。板端为 `marsdog@192.168.5.101`，项目根为
`/home/marsdog/MarsDogPlatform`。当前机器人为 CYVET-CREATOR，固件 **Cyvet-V1.00.000**。
设备 SN 已按用户提供的信息保存到板端私有配置，不写入源码或本指南。

## 当前接入与导航状态（2026-10-13）

当前使用旧版 DHCP/SDK 接入。用户释放 App 控制权后，已通过现有 bridge 进入全零速度 `walking`，状态为 `CONTROLLED(2)`、SDK 错误码 0；原始 `/odom` 约 48～50 Hz。导航包保留原始 Best Effort `/odom`，由现有 TF relay 转发原消息到 Reliable `/odom_nav`，供 Nav2 使用；不修改时间戳、frame、位姿、速度或原始协方差。

静止视觉重定位已恢复。用户通过 RViz 发送的 6 个导航目标全部返回 `Goal succeeded`；其中一次进度检查失败后恢复成功。结束时 walking 的三个速度参数均为零。完整启动、地图选择、WSL RViz 和正常退出顺序见 [远程可视化指南](REMOTE_VISUALIZATION.md)。这些是当前地图的实机链路验证，长期避障、地图精度和相机外参标定仍需后续评估。

## 2026-10-12 初次只读接入记录

以下保留首次接入时的检查结果和故障状态，不作为当前运行状态。

| 检查项 | 本次结果 |
| --- | --- |
| 板端有线网络 | eth0，`192.168.50.1/24` |
| 灵猫 DHCP 租约 | 检查时为 `192.168.50.179`；以后以实际租约为准 |
| 网络可达 | 3 次 Ping 成功，0% 丢包，约 1 ms |
| 官方兼容软件 | 消息、客户端和 bridge 三个 ARM64 包编译通过 |
| 离线测试 | 旧版兼容源码的 2 项官方模拟通信测试通过 |
| 实际 RPC | 能力、系统状态、动作状态三种只读查询均成功 |
| 实际观测 | 最近一次检查累计：IMU 500 条、电池 10 条、bridge 状态 83 条 |
| 电池 | 检查时约 80%，47.32 V |
| Bridge 控制状态 | CONNECTED=1，last_error_code=0，未取得运动控制权 |
| 导航里程计 | 用户确认站立操作后已有 `/odom`；本次未采集该阶段位姿，完整导航仍待验收 |

通信节点当前运行中，未发送运动命令、启动动作或导航。
2026-10-12 追加只读检查：正确订阅旧版原始 `/sensor/observed` 后，本次累计收到
598 条 SensorObserved、599 条 MotionObserved，`/odom` 为 0 条。
598 条原始里程计的 `odom.valid` 全部为 0，最后一帧 `epoch=0`。
桥接源码 `publish_odometry()` 遇到无效标志立即返回，因此这是当前不发布 `/odom` 的直接原因。

官方说明 [Walk 里程计只在 Walk 模式有效](https://github.com/uniubi-ai/uniubi-docs/blob/939d9c7286c35089c3464a2fbd04e67914b510a1/docs/how-to/read-sensor-data.zh-CN.md)。
本次 `query_state` 返回成功但结果为 `{}`，bridge 的 `current_action` 为空，不能据此确定实际姿态或模式。
上述自动检查没有切换动作。随后用户确认站立操作后已有 `/odom`，并已重新坐下；
这是用户提供的实机观察，不是本次自动采集的站立阶段证据。高级动作名仍未确认，
不能把身体站立直接等同于 SDK 的 `standing` 动作。完整导航还需验收位姿连续性与 TF。

更正此前原始订阅检查：当时使用了带设备前缀的话题名，不适用于当前旧版接口；
旧版正确话题为 `/sensor/observed`。此前“未收到原始 ROS 消息”的结果不代表该通道断开。
新的原始数据与 DDS 端点证据保存在 `odom-readonly-diagnosis.json`。
通信读取已确认，导航里程计与实机导航仍待单独验收。

## 软件与网络版本

当前固件低于 Cyvet-V1.00.002，按官方使用旧版 DHCP 接入及兼容 tag。

| 软件 | 固定来源 |
| --- | --- |
| [官方 ROS 2 bridge/client](https://github.com/uniubi-ai/uniubi_ros2/tree/Cyvet-V1.00.001) | tag `Cyvet-V1.00.001`，commit `e497ca0b06ffd20d1f0d088b935fe0bce3459050` |
| [官方消息](https://github.com/uniubi-ai/uniubi_robot_msgs) | `0716257e262c4b3f5d8424c6ddf284309fcac7fc`，与 tag 的 dependencies.lock 一致 |

源码归档按 SHA256 核验，原始解包保存在 `preserved/`，构建副本在 `source/`。
原先为新固件编译的 main 版本保留在 `out/rk3588-lingmao-communication`；
当前设备使用独立的 **`out/rk3588-lingmao-communication-legacy`**，避免混用接口和缓存。
现代版本此前的 8 项离线 PASS 是另一份源码的结果，不当作本次旧版验收。

## 当前目录

```text
out/rk3588-lingmao-communication-legacy/
├─ archives/、preserved/、source/  固定源码及工作副本
├─ build/、install/               旧版独立构建产物
├─ source-provenance.json         固定提交与归档 SHA256
├─ native-env.sh                  内部隔离构建环境
├─ use-lingmao-communication.sh    实际通信环境入口
├─ robot.env、device-profile.json 本地设备身份配置，权限 600
├─ configure-lingmao-network.sh   管理员网络配置入口
├─ start-lingmao-bridge.sh         通信节点启动入口
├─ verify-lingmao-readonly.py      实际只读通信验证
├─ verify-lingmao-install.sh       离线安装及模拟通信验证
├─ bridge.log、bridge-launch.pid  当前节点日志和启动 PID
├─ readonly-verification.json     最新实际查询与数据统计
├─ sensor-observation.json        此前话题名不匹配的订阅记录
├─ odom-readonly-diagnosis.json   正确原始话题及里程计有效性检查
├─ build-status.json              本次构建与 OOM 记录
├─ memory-samples.jsonl           构建内存采样
└─ verification/                 官方离线测试输出
```

## 旧版网络配置与维护

本次用户已在板端执行以下管理员入口：

```bash
sudo bash /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/configure-lingmao-network.sh --legacy-dhcp
```

脚本创建单独的 `lingmao-legacy-ethernet` NetworkManager 配置和
`marsdog-lingmao-dhcp.service`。DHCP 只绑定 `eth0`，地址池为
`192.168.50.100`～`192.168.50.200`；不在 Wi-Fi 提供 DHCP，也不将板子作为机器狗的默认路由或 DNS。
板端继续使用 `wlan0` 的原默认路由上网和 SSH。没有开启路由转发、NAT 或改机器狗内部网络。

官方参考流程见 [旧版 DHCP 接入](https://github.com/uniubi-ai/uniubi-docs/blob/939d9c7286c35089c3464a2fbd04e67914b510a1/docs/development-setup/README.zh-CN.md#legacy-dhcp)。
此设备不应运行 `--modern-static` 或套用 `172.29.140.2/24` 的新版地址。

查看实际租约和服务：

```bash
ip -br address show eth0
cat /var/lib/marsdog-lingmao-dhcp/leases
systemctl status marsdog-lingmao-dhcp --no-pager
journalctl -u marsdog-lingmao-dhcp -n 20 --no-pager
```

NetworkManager 配置和 DHCP 服务已设置开机启用，**尚未重启验证**。
若 DHCP 服务已启动而尚无租约，可重新插拔机器狗网线触发 DHCP 请求。
回退时停止/禁用自己的 DHCP 服务，关闭 `lingmao-legacy-ethernet` 的自动连接，
再按 `network-backups/connections-*.txt` 恢复原 Ethernet 连接；原 Wi-Fi 和 Ethernet 配置没有删除。

## 加载环境与启动通信

2026-10-13 已将统一双网卡环境入口加入板端 `~/.bashrc`，并验证新交互式终端自动加载成功。
新开终端无需再次手动加载；已有终端可执行 `source ~/.bashrc`，或直接执行：

~~~bash
source /home/marsdog/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh
~~~

它加载导航依赖和旧版 bridge，设置 Cyclone DDS、Domain 42、非 localhost 模式，
通过当前默认路由接口和 `eth0` 接通建图与底盘 DDS，加载环境时自动刷新本机地址，不再绑定电脑 IP。板端两块接口都支持 SPDP 发现，监听两块接口发现组播，应用数据使用单播，并从私有 `robot.env` 加载目标 SN。
`start-lingmao-bridge.sh` 内部仍可使用原 `eth0` 专用 SDK 环境，已经验证与统一建图环境互通。
本次原 `.bashrc`、DDS XML、生成器及环境脚本备份在 `out/rk3588-remote-visualization/backups/dds-connect-20261013-115120`。
已安装系统 Avahi 发现标识；电脑入口根据板端身份自动找到当前 IP。Wi-Fi 地址变化不需要重新配置灵猫 Ethernet DHCP。配置变更只对新进程生效，已经启动的节点需要正常退出后重启。
自动加载环境不会自动启动 bridge 或发送运动命令。

本次已实际验证里程计、分层 TF、RTAB-Map 地图输出及电脑接收；完整启动步骤与边界见 [远程可视化指南](REMOTE_VISUALIZATION.md)。

通信节点已经运行，不要再启动第二份。重启板子后，或关闭节点后，在板端重新启动：

```bash
bash /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/start-lingmao-bridge.sh
```

前台运行时用 Ctrl+C 关闭。本次后台节点的日志和 PID 在上面的 bridge 文件中。
需要关闭本次后台节点时，先核对 PID 仍是该 ros2 launch，再发送 SIGINT，避免误停其他进程。
bridge 当前没有配置开机自启；网络服务自启不等于通信节点自启。

官方 bridge 启动后连接及读取观测，不自动取得运动控制权。App 释放控制权后，本设备会趴下并暂停有效里程计；需要下面的明确接管步骤。
`motion_high_level_client_example` 和交互 CLI 会申请控制权，不用于本次只读验证。

## SDK 接管与里程计恢复

保持 bridge 运行，先在 App 释放控制权，确认没有执行中的导航目标，在另一个板端终端执行：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 service call /motion/start_action uniubi_motion_bridge/srv/StartMotionAction \
  '{action: walking, params_json: "{\"lineVelocityX\":0.0,\"lineVelocityY\":0.0,\"velocity\":0.0}"}'
timeout 10s ros2 topic echo /motion/status --no-daemon --once
timeout 10s ros2 topic echo /odom --no-daemon --once --qos-reliability best_effort
~~~

确认 `success: true`、`control_state: 2`、`current_action: walking` 和有效里程计后，再启动建图或导航。服务会通过已有 bridge 申请控制权并进入全零速度 walking；不会发送非零行走速度。每次 bridge 重启或控制权切换后重新检查，普通新开终端只加载环境即可。

按[官方高级控制说明](https://github.com/uniubi-ai/uniubi-docs/blob/main/README.zh-CN.md#安全说明)，先进入全零速度 walking，再调用其他受状态机约束的非趴下动作。本设备先调用 standing 曾被拒绝（`kActionRejected(8)`），不能用它代替这一初始化步骤。

结束全部导航时，先取消目标并正常退出建图/导航，再在 bridge 仍运行时释放：

~~~bash
ros2 service call /motion/release_control std_srvs/srv/Trigger '{}'
~~~

本设备释放后会趴下，里程计可能暂停；之后再退出相机和 bridge。仅切换建图/定位模式时保留控制权和 A/B 进程。

## 单独模型与 TF

UWB 跟随等测试不需要启动建图；保持通信桥和有效里程计，在另一个板端终端执行：

~~~bash
source "$HOME/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh"
ros2 launch robot_slam_bringup robot_tf.launch.py \
  robot:=lingmao \
  robot_config:="$HOME/.config/marsdog/robots/lingmao.yaml"
~~~

它不申请控制权、不启动相机或 UWB 串口。TF 已单独运行时，后续 nav.launch.py 加 `start_tf:=false`，避免重复发布。

## 重复实际只读验证

保持 bridge 运行，新终端加载同一环境后执行：

```bash
source /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/use-lingmao-communication.sh
python3 /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/verify-lingmao-readonly.py \
  --seconds 15 --output /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/readonly-verification.json
```

程序只调用能力、系统状态和动作状态查询，统计 `/motion/status`、`/imu/data`、
`/battery_state`、`/odom`；不调用取权、动作、急停或速度发布接口，不输出原始系统 JSON 或密钥。
RPC 成功且状态/IMU 有数据，才记通信 PASS；`navigation_odom_available` 单独报告。

## D435i 与 UDP 接收缓冲评估（2026-10-12）

相机已在 USB 3 链路被识别，`lsusb -t` 显示 5000M，驱动报告 USB 3.2。
当前 RealSense ROS 包版本为 4.58.4，相机固件为 5.15.1.55。
本次仅在隔离 Domain 86、与实际通信相同的 eth0 上临时启动相机并读取数据；
未启动 RTAB-Map、Nav2、视差投影或运动控制，结束后只关闭了本次相机进程。

60.08 秒统计：左右 640×480 mono8 图像各 900 帧，约 15 Hz；最大接收间隔约 0.10 秒。
单图数据区为 307,200 字节。左右 CameraInfo 有数据；
所检查的左图与左 CameraInfo 发布者均为 Reliable，Best Effort 图像订阅能正常接收。
UDP `RcvbufErrors`、`InErrors` 增量为 0，所采样相机/订阅者 socket 的丢弃计数为 0，
最低可用内存约 6.50 GiB。
这只是轻负载相机接收结果，不是完整 RTAB-Map/点云/导航的长期稳定性验收。

### 仍建议扩大接收缓冲上限

初次相机评估时内核 `net.core.rmem_max=212992`、`rmem_default=212992`；
实际 Cyclone DDS socket 的 `ss` 显示 `rb425984`，约 416 KiB。
以前 GO2 记录中的这项限制属于板端 Linux/DDS 配置，也会影响灵猫的大消息接收。
建议先将上限放开到 8 MiB，随后在实际负载下检查订阅间隔和 socket 丢弃计数：

```bash
sudo sysctl -w net.core.rmem_max=8388608
```

持久化可在 `/etc/sysctl.d/99-marsdog-ros2-udp.conf` 中添加下面一行，
保留文件中其他已有配置，再执行 `sudo sysctl -p /etc/sysctl.d/99-marsdog-ros2-udp.conf`：

```text
net.core.rmem_max = 8388608
```

初次相机评估未修改系统参数，后续已通过管理员入口应用，详见下方实施状态。上限不是为每个 socket 预分配 8 MiB，
也不是把默认接收缓冲全部改为 8 MiB。设置上限后应重新启动相机和相关大消息节点，
让它们重新申请 socket 缓冲；已有 socket 不会因修改上限自动扩大。
Cyclone DDS 默认请求 1 MiB，Linux 的 `ss` 显示值通常包含加倍后的内核计账。
若在完整负载下仍丢包，再评估更大的实际请求与传输方案。

### 旧 GO2 记录的配置说明更正

`SocketReceiveBufferSize` 在 Cyclone DDS 0.10.5 不是只读项，它通过属性设置。
例如下面的语法在当前板端、loopback 隔离域中创建节点成功：

```xml
<Internal>
  <SocketReceiveBufferSize min="default" max="8 MiB"/>
</Internal>
```

把 `8 MiB` 放在元素正文中会报 `no data expected`，当前板端已离线复现。
本次没有将这个可选片段写入实际通信环境，仍保留现有 eth0、Domain 42 与 DontRoute 配置。
格式依据 [0.10.5 官方配置定义](https://github.com/eclipse-cyclonedds/cyclonedds/blob/0.10.5/etc/cyclonedds.xsd)。

当前 Humble 安装的 `ros2 topic hz` 源码使用 `qos_profile_sensor_data`（Best Effort），
不能沿用旧记录中“默认适配发布者为 Reliable”的说法。
排查时应直接确认发布端与实际业务订阅端 QoS，不以另一个 hz/echo 订阅者的成功代替业务节点验收。
当前 `nav.launch.py` 已配置图像 Best Effort、CameraInfo Reliable；与本次观察的相机发布者兼容，
尚无依据统一切换为 Reliable。它直接消费双目图像，不包含旧 GO2 的独立视差投影链路。

### 相机 IMU 与安装 TF

相机 IMU 本次为 0 条；日志提示 `No HID info provided, IMU is disabled`。
内核 6.1.172 的 `CONFIG_HID_SENSOR_HUB` 未启用，未找到相应模块；
现有 IIO 设备是板端 saradc，不是 D435i IMU。这是当前 Linux HID/IIO 路线缺少支持的证据，
不是扩大 UDP 缓冲能够解决的问题。尚未修复或验证 IMU；需要 OpenVINS 时再补齐驱动/后端支持，
不直接套用通用 Ubuntu 的内核更新命令。

当前 `nav.launch.py` 用外部底盘里程计和双目图像，不订阅相机 IMU。
仅运行这条路线时，相机可采用以下图像配置：

```bash
source /home/marsdog/MarsDogPlatform/robotics/tools/remote_visualization/use-remote-board.sh
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=false enable_depth:=false \
  enable_infra1:=true enable_infra2:=true \
  enable_gyro:=false enable_accel:=false \
  enable_sync:=true depth_module.infra_profile:=640x480x15 \
  depth_module.enable_auto_exposure:=true
```

临时检查已停止相机，未留下第二份驱动。正式运行前应确认没有其他相机节点占用设备。
后续 URDF 配置已按用户要求采用模型估计初版：`base_link→camera_link=[0.289,0,0.114] m`，
朝向暂按水平向前；这些值仍需要实测调整。机身站姿高度按用户 2026-10-14 校正改为 `0.36 m`，较原值下调 2 cm。
当前相机安装边由独立 robot_tf.launch.py 中的 robot_state_publisher 发布，导航默认包含同一入口；相机内部光学 TF 仍由相机驱动负责。2026-10-14 按用户提供的位置新增 `camera_link→uwb_link` 固定关节，偏移 `[-0.04,0,-0.05] m`、朝向一致，由同一模型发布器负责。
RTAB-Map 改以分层后的 `base_footprint` 为基座，继续通过 TF 获取位姿，不使用不可靠协方差。

证据位于板端当前输出目录的 `camera-receive-assessment.json`、`camera-receive-assessment.log`
和 `cyclonedds-buffer-syntax-check.json`；Windows JSON 副本在
`D:\work\资料归档\硬件验证\灵猫通信\2026-10-12`。


### UDP 优化实施入口与 IMU 占用检查

UDP 配置已准备为可复用脚本 `configure-ros2-udp-buffer.sh`，
源码在 `robotics/tools/lingmao/`，板端运行副本在当前 legacy 输出目录，
Windows 副本在 `D:\work\scripts\rk3588-lingmao-communication`。
脚本只修改接收缓冲上限，备份原值及本脚本管理的配置文件，
写入 `/etc/sysctl.d/99-marsdog-ros2-udp.conf`，不重启任何服务。
同名未受脚本管理的文件会被拒绝覆盖。

```bash
sudo bash /home/marsdog/MarsDogPlatform/out/rk3588-lingmao-communication-legacy/configure-ros2-udp-buffer.sh --apply
```

管理员执行后已检查：`rmem_max=8388608`，持久化文件存在且内容正确；
新创建的 DDS socket `rb=2097152`（2 MiB），采样丢弃计数为零。
8 MiB 是允许申请的上限，当前 Cyclone DDS 默认请求 1 MiB，Linux 按加倍计账显示 2 MiB。
配置会在开机由 sysctl 加载；本次未重启验证。未强制重启已有通信节点，已有 socket 保留原缓冲。
脚本打印备份目录，原内核值在 `rmem_max.before`，
旧文件存在时保存在 `sysctl.conf.before`，不存在时留 `config-was-absent` 标记。
回退时以该次备份恢复/移除本脚本管理的配置文件，并用 `sudo sysctl -w net.core.rmem_max=<原值>` 恢复；
不删除其他 sysctl 配置。

本次板端占用检查：D435i 的接口是 USB HID（检查时 `/dev/hidraw2`，绑定 hid-generic），
`/dev/ttyUSB0` 是独立 FTDI USB UART；普通用户的 `fuser` 未发现二者的占用者，
此结果不代表检查了所有 root 进程的文件描述符。
Ubuntu 的 `screen-reader-enabled=false`，Orca 没有运行，
speech-dispatcher 服务为 inactive。没有发现屏幕阅读器或串口占用引起相机 IMU 失效的证据，
因此没有停用其他服务或机器人模式。内核缺失 HID Sensor Hub/IIO 支持仍待修复。
证据为 `imu-ownership-diagnosis.json`。


### 恢复 D435i IMU 的建议路径（尚未实施）

优先尝试补齐与当前 LubanCat 内核 `6.1.172` 匹配的 HID/IIO 模块。
当前 `/lib/modules/6.1.172/build` 指向 `/usr/src/linux-headers-6.1.172`，
对应头文件、生成的内核配置和 `Module.symvers` 存在，`CONFIG_MODULES=y`、
`CONFIG_MODVERSIONS=y`。驱动 C 源码不在这个头文件包中，需要取得匹配的厂商内核源码；
编译成功与实际加载成功必须分别验证，不能仅凭版本号相同推断 ABI 匹配。

需要的组件配置包括：

```text
CONFIG_HID_SENSOR_HUB=m
CONFIG_HID_SENSOR_IIO_COMMON=m
CONFIG_HID_SENSOR_IIO_TRIGGER=m
CONFIG_HID_SENSOR_ACCEL_3D=m
CONFIG_HID_SENSOR_GYRO_3D=m
```

实施顺序是：取得匹配源码 → 独立目录补编译模块 → 核对 vermagic、符号版本与依赖 →
管理员安装并加载 → 重新插拔相机并确认加速度计/陀螺仪 IIO 设备 →
启动 RealSense ROS 驱动并实际订阅 IMU。
优先评估模块方式；只有模块方案无法满足依赖时，才评估更换完整内核。
本次没有编译、安装或加载这些模块。
构建条件依据 [Linux 外部模块文档](https://docs.kernel.org/kbuild/modules.html)，
HID/IIO 组件名亦见 [RealSense 官方驱动准备源码](https://github.com/realsenseai/librealsense/blob/master/scripts/patch-realsense-ubuntu-L4T.sh)；
该脚本面向 NVIDIA，不能直接在 RK3588 上运行。

驱动支持修复后，才使用完整相机启动命令中的以下参数：

```text
enable_gyro:=true enable_accel:=true unite_imu_method:=2
```

最终验收检查 `/camera/camera/imu` 的实际持续消息、时间戳、角速度和加速度，
同时复核双目图像；仅话题名存在不算 IMU 可用。

备选是单独编译同版本 librealsense 的 `FORCE_RSUSB_BACKEND=ON` 用户态 USB 后端，
并让相机 ROS 驱动加载这套独立安装前缀，再做相机/IMU 实测。
它可以避免依赖现有 HID/IIO 接收路线，但本板兼容性和稳定性尚未验证，
暂不覆盖当前可用的双目驱动。现有 SDK 为 librealsense 2.58.4、ROS 驱动为 4.58.4。

## 与统一导航入口配合

继续使用 `nav.launch.py`，先打印配置检查：

```bash
ros2 launch robot_slam_bringup nav.launch.py robot:=lingmao print_config:=true
```

当前灵猫 profile 接标准 `/odom` 和 `/cmd_vel`，保留官方 Odometry 的原始 `child_frame_id=base_link`。
同一 relay 将有效平面位姿发布为 `odom→base_footprint`，再发布用户配置的 `base_footprint→base_link`。
机身 URDF 与相机挂在 base_link，Nav2/RTAB-Map 使用 base_footprint；每条 TF 保持一个发布者。
用户已确认站立后 `/odom` 恢复，仍需验证位姿连续性、TF 和完整导航链路。
相机安装外参、D435i 图像与 CameraInfo 仍按实物准备；完整说明见 [三机器人配置](ROBOT_PROFILES.md)。

## 编译复现与离线检查

源码工具在 `robotics/tools/lingmao/`，Windows 交付在
`D:\work\scripts\rk3588-lingmao-communication`。所有脚本保留原名称；用
`LINGMAO_PROFILE=legacy|modern` 选择独立输出目录，默认 legacy 对应当前设备。
公共监控仍复用 `out/rk3588-slam-features/build-navigation-monitored.py` 和
`build-openvins-monitored.py`，不重复复制；其 Windows 公共副本在已有同名 scripts 子目录。
基础依赖沿用本板的 `out/rk3588-navigation/native-env.sh`，不是从空系统独立安装。

```bash
export MARSDOG_ROOT=/home/marsdog/MarsDogPlatform
export LINGMAO_PROFILE=legacy
mkdir -p "$MARSDOG_ROOT/out/rk3588-lingmao-communication-legacy"
cp "$MARSDOG_ROOT/robotics/tools/lingmao/"*.py \
   "$MARSDOG_ROOT/robotics/tools/lingmao/"*.sh \
   "$MARSDOG_ROOT/out/rk3588-lingmao-communication-legacy/"
python3 "$MARSDOG_ROOT/out/rk3588-lingmao-communication-legacy/prepare-lingmao-communication.py"
python3 "$MARSDOG_ROOT/out/rk3588-lingmao-communication-legacy/build-lingmao-communication-monitored.py"
bash "$MARSDOG_ROOT/out/rk3588-lingmao-communication-legacy/verify-lingmao-install.sh"
```

本次旧版构建两任务，168.9 秒完成，最低可用内存 5.48 GiB，Swap 使用零，OOM 计数增量零。
有明显压力时监控降到一任务，进入一任务后继续并报告。
离线测试使用 loopback 和独立 DDS 域，旧版官方源码包含 1 项客户端与 1 项 bridge 测试；
不连接机器人 Domain 42。实际只读验证独立记录，二者不能互相替代。


## 当前灵猫模型与坐标系

URDF/TF 已在后台通过 nav.launch.py 的 frames_only 模式运行，没有启动相机或导航，也没有发送运动命令。
个人可调配置为 `/home/marsdog/.config/marsdog/robots/lingmao.yaml`，发布完整建图/导航时也应传入该 robot_config，
并先关闭原模型 launch，避免重复发布者。官方资产及相机初版来源、0.36 m 高度和关节别名见 [三机器人配置](ROBOT_PROFILES.md)。
实际相机安装与关节 TF 已收到；坐下无 /odom 时不伪造 odom→base_footprint。
本次完整链路 PASS 来自隔离域合成数据，完整实机导航仍待验收。
