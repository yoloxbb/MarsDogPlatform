# RK3588 Nav2、MPPI、STVL 与 GO2 描述包编译和使用

核对日期：2026-10-11。适用板端：`marsdog@192.168.5.87`，Ubuntu 22.04 ARM64、ROS 2 Humble。VINS-Fusion 本次明确跳过。

## 选择源码编译的原因

Nav2 源码编译方便修改 MPPI、规划器和自定义插件，并能固定完整版本；同版本、同参数下，不会因为采用源码编译自动提高精度。未修改算法时，官方 ARM64 二进制也是合理选择。本次将 Nav2 固定到 Humble 1.1.20，使用 Release 构建。MPPI 使用 CPU 和 xtensor/xsimd，本流程不启用 RK3588 NPU。

## 固定的源码

| 项目 | 版本 / 提交 | 来源 |
|---|---|---|
| Navigation2，包括 MPPI、Smac、DWB、Constrained Smoother、DenoiseLayer 等 | 1.1.20；`a097086719c88f781aa59788eca29ac6ca5e56db` | [Nav2 官方仓库](https://github.com/ros-navigation/navigation2) |
| STVL | 2.3.4；`92896fe9ea994260bf34f1fa7b7735f3804cfc6f` | [STVL 官方仓库](https://github.com/SteveMacenski/spatio_temporal_voxel_layer) |
| GO2 描述包 | `1519be2485f63e54349b85f6f766b574ea6ff700` | 用户指定的 [GO2 仓库](https://github.com/sun-under-bird/go2) |

GO2 仓库只构建 `src/go2_description`；其他驱动、键盘遥控和桥接包不纳入这次构建。URDF 和模型几何保持来源版本。STVL 使用 Humble ARM64 `openvdb_vendor` 的 OpenVDB 10.0.1，不重复编译大型 OpenVDB 源码。编译参数显式指定该 vendor 前缀，避免误用 Ubuntu OpenVDB 8 的头文件。

同时编译 `robotics/ros2/src` 的 9 个自有包、UWB 消息和通用串口库，以及 `marsdog_voice_interaction` 的 ROS 接口、`marsdog_observability`。UWB 厂商硬件驱动编译开关为 `OFF`；语音包的 ROS 接口可用不代表 ASR/TTS 模型和音频运行环境已验收。

RealSense ROS 驱动、SDK、robot_localization、图像处理、BehaviorTree.CPP v3、OpenVDB/TBB 等依赖采用固定版本 ARM64 包的独立解包前缀。依赖包用来补齐编译和运行闭包；Nav2、STVL 实际采用 `install` 中本次源码产物。没有向系统 `/opt/ros/humble` 或 `/usr` 写入安装文件。

## 目录

总仓库：`/home/marsdog/MarsDogPlatform`。本次根目录：`out/rk3588-navigation`。

```text
out/rk3588-navigation/
├── archives/                 # 固定提交的原始源码压缩包
├── preserved/                # 原始解包源码
├── source/                   # 实际编译的工作副本
│   ├── navigation2/
│   ├── spatio_temporal_voxel_layer/
│   ├── go2/src/go2_description/
│   ├── robotics/             # 9 个自有 ROS 包
│   ├── uwb/
│   ├── marsdog_voice_interaction/
│   ├── marsdog_observability/
│   └── navigation_build_check/ # 无硬件插件加载检查
├── dependencies/
│   ├── downloads/            # ARM64 原始 deb 包
│   ├── source-build-downloads/
│   ├── raw/                  # 原始依赖解包
│   └── view/                 # 路径修正后的构建/运行前缀
├── build/                    # 分包 CMake 构建目录
├── install/                  # 分包安装产物
├── logs/                     # colcon 日志
├── native-env.sh             # 内部构建环境
├── use-navigation.sh         # 用户运行环境入口
├── source-provenance.json
├── robotics-source-provenance.json
├── dependency-lock.json
├── build-status.json
├── memory-samples.jsonl
└── verification.json
```

OpenVINS 和 RTAB-Map 仍保留在原有 `out/rk3588-openvins`、`out/rk3588-rtabmap`。新的加载入口会同时加载它们及导航环境。

## 加载与检查

每个新终端，在板端 Bash 中执行：

```bash
source /home/marsdog/MarsDogPlatform/out/rk3588-navigation/use-navigation.sh
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_mppi_controller
ros2 pkg prefix spatio_temporal_voxel_layer
ros2 pkg prefix go2_description
```

`use-navigation.sh` 保留调用终端的 ROS Domain 和 localhost 设置，不修改 `.bashrc`。不要把内部 `native-env.sh` 的隔离测试 Domain 当成实机部署 Domain。

只解析启动参数，不启动相机或底盘：

```bash
ros2 launch robot_slam_bringup nav.launch.py --show-args
ros2 launch robot_slam_bringup go2_d435i_slam_nav2.launch.py --show-args
ros2 launch robot_slam_bringup openvins_rtabmap.launch.py --show-args
ros2 launch realsense2_camera rs_launch.py --show-args
```

主要 `nav.launch.py` 不启动 RealSense、WIT 或底盘驱动，GO2 组合入口也需要外部图像、IMU 和 TF。描述包安装后不会自动启动 robot_state_publisher；应由部署入口明确启动。模型路径为 `$(ros2 pkg prefix --share go2_description)/urdf/go2_description.urdf`，实物的相机安装位置和关节状态仍需核对。

当前 Lite3 `nav.yaml` 使用 Nav2 MPPI、Smac Hybrid、Constrained Smoother、STVL 和自定义恢复；GO2 `go2_nav2.yaml` 保留 DWB/Navfn 默认组合。编译 MPPI 不会自动切换 GO2 的控制器，也不会修改 RTAB-Map 的特征和优化策略。

## 复现构建

前提：已有通过验证的本板 OpenVINS 与 RTAB-Map 构建，及原有 `out/rk3588-slam-features` 基础辅助脚本。新增脚本位于同一目录；Windows 专用脚本统一保存在 `D:\work\scripts\rk3588-slam-features`，使用说明见 `D:\work\scripts\脚本使用说明.md`。这些脚本及离线依赖是本机交付资源，不随本仓库分发；在新机器复现前需先取得完整脚本目录和锁文件。

```bash
bash /home/marsdog/MarsDogPlatform/out/rk3588-slam-features/reproduce-navigation-build.sh
```

主流程依次获取固定源码、准备工作副本、准备依赖、补齐开发包、进行受监控构建，再执行无硬件验证。已有缓存按锁文件校验，已存在的工作副本不会被原始源码自动覆盖。新环境首次准备依赖仍需要网络；板端网络慢时可在 Windows 下载同版本档案，经 apt 元数据哈希校验后传入 `archives` 或 `dependencies/downloads`。

`prepare-native-navigation.py` 和 `build-navigation-monitored.py` 导入已有的 `prepare-native-openvins.py`、`build-openvins-monitored.py`；它们的完整源码集中在同一个 Windows 脚本目录，部署到板端时也需保留同目录的导入关系。SLAM 编译目录及其依赖不能先删除。

## 修改与增量编译

修改上面列出的 `out/rk3588-navigation/source/...` 工作副本后，执行：

```bash
python3 /home/marsdog/MarsDogPlatform/out/rk3588-slam-features/build-navigation-monitored.py
source /home/marsdog/MarsDogPlatform/out/rk3588-navigation/use-navigation.sh
```

它遍历同一组包，CMake 增量编译只更新变化的输入和受影响目标。更改接口或导出头文件时，这比只选择一个包更能覆盖依赖方。更改总仓库原始 `robotics/ros2/src` 后，要先核对与工作副本的差异，再同步修改；准备脚本不会静默覆盖已有副本。请把最终业务修改保留回原始仓库。

普通 colcon 也可以编译，路径分开不会阻止构建。仅修改 MPPI 内部实现时，可使用同一输出目录：

```bash
source /home/marsdog/MarsDogPlatform/out/rk3588-navigation/use-navigation.sh
export CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1
colcon --log-base /home/marsdog/MarsDogPlatform/out/rk3588-navigation/logs build \
  --base-paths /home/marsdog/MarsDogPlatform/out/rk3588-navigation/source/navigation2 \
  --build-base /home/marsdog/MarsDogPlatform/out/rk3588-navigation/build \
  --install-base /home/marsdog/MarsDogPlatform/out/rk3588-navigation/install \
  --executor sequential --packages-select nav2_mppi_controller \
  --cmake-args -DCMAKE_BUILD_TYPE=Release '-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -g0' \
  -DBUILD_TESTING=OFF
```

这条普通命令没有自动内存监控；完整受监控入口优先。不要同时运行两个构建命令。

## 内存监控

这块板实际 RAM 约 7.7 GiB，Swap 为已有 2 GiB 文件与 25 GiB 构建文件，总量约 27 GiB；本次没有发现 zram。根分区是本板当前 eMMC/ext4，容量与此前“15 GiB RAM + NVMe”的示例不同。

构建从包间串行、包内 `-j2` 开始，编译进程 nice 为 10，每 2 秒记录可用内存、Swap、交换 I/O 与 PSI。可用内存连续 3 个采样低于 1.5 GiB，或明显 PSI/Swap 压力时，停止本脚本自己的双任务构建进程组，并在同一目录以 `-j1` 增量继续。低于 768 MiB 时立即降并发。单任务时按用户要求继续，只监控与报告，不因内存压力自动停止。脚本保留上次的并发数。

查看状态：

```bash
python3 /home/marsdog/MarsDogPlatform/out/rk3588-slam-features/navigation-progress.py
cat /home/marsdog/MarsDogPlatform/out/rk3588-navigation/build-status.json
tail -n 20 /home/marsdog/MarsDogPlatform/out/rk3588-navigation/controller.log
```

## 验证范围和结果

以下为 2026-10-11 补齐依赖时的验证记录，并非每次提交重新执行的结果。54 个包构建通过；原生库/可执行文件动态链接检查 210 个通过，导航插件构造 22 个通过。当时 Lite3（MPPI/STVL/Smac/自定义恢复）和旧 GO2（DWB/Navfn）两套配置各 7 个服务器配置到 inactive，通过。GO2 模型 31 个 link、30 个 joint 和全部引用网格资源校验通过。当前三机器人统一 MPPI 入口的验证范围见 [三机器人配置与切换指南](ROBOT_PROFILES.md)。

编译监控记录的最低可用内存约 **1.94 GiB**，最大 Swap 使用约 **17.2 MiB**。构建结束 OOM 计数增量为 0。实际并发以 `build-status.json` 和 `memory-samples.jsonl` 为准。Qt 运行文件补齐和 OpenVDB 版本选择已纳入复现脚本，原始 vendor 源码没有算法补丁。

无硬件验证使用独立 ROS Domain 213、localhost 通信，检查包发现、原生 ELF 动态链接、22 个导航插件构造、启动参数解析、GO2 URDF/网格资源、Python 消息接口导入。插件仅构造；另在独立 Domain 219 中验证 Lite3 与 GO2 两套参数的 7 个导航生命周期服务器配置到 inactive。检查不激活运动控制器、不发送导航目标。

手动重复无硬件验证：

```bash
source /home/marsdog/MarsDogPlatform/out/rk3588-navigation/use-navigation.sh
ROS_DOMAIN_ID=213 ROS_LOCALHOST_ONLY=1 python3 \
  /home/marsdog/MarsDogPlatform/out/rk3588-slam-features/verify-native-navigation.py
```

这不等于 D435i 实机建图、障碍避让、底盘速度链路或导航运动验收。VINS-Fusion 入口保留，`vins` 依赖本次跳过。

总仓库 `tools/dev.py check` 中架构检查和 Python 测试通过；标识目录仍报告已有的 `catalog sources changed`，与补齐依赖之前一致，本次没有擅自刷新该业务基线。详见 `out/rk3588-navigation/platform-check.log`。

## 三机器人统一导航配置

Lite3、GO2 和宇泛灵猫现在统一使用 `robot_slam_bringup/nav.launch.py`，通过 `robot:=lite3|go2|lingmao` 选择配置，共用 MPPI、STVL、Smac Hybrid 和 Constrained Smoother。未指定 robot 时保留 Lite3 默认参数。详见 [三机器人配置与切换指南](ROBOT_PROFILES.md)。
