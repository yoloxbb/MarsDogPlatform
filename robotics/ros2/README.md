# robotics ROS 2 构建与运行说明

核对日期：2026-10-12。10 个自有包的源码统一在 `robotics/ros2/src`，不再按旧工作空间分开查找。此处说明构建方法；选择 launch 前应阅读对应包的 README。

## 本板已完成的导航环境

`out/rk3588-navigation` 已构建 Nav2、MPPI、STVL、GO2 描述包和 2026-10-11 当时的 9 个包；RealSense、robot_localization 和图像处理运行依赖已补齐，VINS-Fusion 本次跳过。新增 [完整构建与使用说明](NAVIGATION_BUILD.md) 记录固定源码、依赖锁、内存监控、增量编译和验证范围。

2026-10-12 新增的 `robot_local_motion` 默认关闭，复用现有局部 MPPI。其独立安装与更新后的 Action 包位于 `out/rk3588-local-motion`，加载 `out/rk3588-local-motion/use-local-motion.sh`。旧导航安装未覆盖；详见 [通用局部运动接口与仿生场景参数指南](src/robot_local_motion/README.md)。

```bash
source /home/marsdog/MarsDogPlatform/out/rk3588-navigation/use-navigation.sh
```

下面的分包示例用于另建研发输出；日常使用本次产物时不需要再创建 `out/rk3588-robotics`。

## 目录与环境

本板总仓库：`/home/marsdog/MarsDogPlatform`。以下示例将自有机器人包的产物放在 `out/rk3588-robotics/{build,install,log}`，这是建议的新输出目录，不表示已经构建完成。OpenVINS 和 RTAB-Map 原有输出保持在各自目录。

在板端 Bash 中设置：

```bash
export MARS_ROOT=/home/marsdog/MarsDogPlatform
export ROBOTICS_OUT="$MARS_ROOT/out/rk3588-robotics"
source /opt/ros/humble/setup.bash
# 使用本板已编译的 RTAB-Map/OpenVINS 时加载：
source "$MARS_ROOT/out/rk3588-rtabmap/use-rtabmap.sh"
mkdir -p "$ROBOTICS_OUT"
```

加载脚本包含原生依赖环境；保留调用者已有的 `ROS_DOMAIN_ID` 和 `ROS_LOCALHOST_ONLY`。其他机器应加载自己的 ROS 2 和依赖安装前缀，不能照搬本板 ARM64 二进制。不同终端需加载一致的 overlay、RMW 和 ROS Domain。

## 分包构建

例如只编译 IMU、V4L2 相机和人体定位包：

```bash
export CMAKE_BUILD_PARALLEL_LEVEL=2
export MAKEFLAGS=-j2
colcon --log-base "$ROBOTICS_OUT/log" build \
  --base-paths "$MARS_ROOT/robotics/ros2/src" \
  --build-base "$ROBOTICS_OUT/build" \
  --install-base "$ROBOTICS_OUT/install" \
  --packages-select wit_imu stereo_v4l2_camera person_3d_localization \
  --symlink-install --executor sequential \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
source "$ROBOTICS_OUT/install/local_setup.bash"
```

`--executor sequential` 限制包间并发；`CMAKE_BUILD_PARALLEL_LEVEL`/`MAKEFLAGS` 限制包内编译并发。这些命令本身不自动监控内存。另开终端用 `watch -n 2 'free -h; swapon --show'` 观察；大型编译需要完整监控时参照总仓库 `out/rk3588-slam-features` 的已验证构建脚本，不能把其固定的 OpenVINS/RTAB-Map 构建目标直接视为本目录的通用监控器。

### UWB 链路

`go2_uwb_local_follow` 在编译时需要 `uwb_aoa_pkg`。有已构建依赖时先加载该前缀；没有时先复制 `.external/uwb` 到输出目录，再将工作副本纳入本次源码发现范围。这样保留原始仓库并记录关键输入指纹；已有副本时不覆盖，更新依赖需先核对差异：

```bash
mkdir -p "$ROBOTICS_OUT/source"
if [ ! -e "$ROBOTICS_OUT/source/uwb" ]; then
  cp -a "$MARS_ROOT/.external/uwb" "$ROBOTICS_OUT/source/uwb"
  sha256sum "$MARS_ROOT/.external/uwb/package.xml" \
    "$MARS_ROOT/.external/uwb/CMakeLists.txt" > "$ROBOTICS_OUT/source/uwb-source-inputs.sha256"
fi
colcon --log-base "$ROBOTICS_OUT/log" build \
  --base-paths "$MARS_ROOT/robotics/ros2/src" "$ROBOTICS_OUT/source/uwb" \
  --build-base "$ROBOTICS_OUT/build" \
  --install-base "$ROBOTICS_OUT/install" \
  --packages-up-to go2_uwb_behavior \
  --symlink-install --executor sequential \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_UWB_VENDOR_DRIVER=OFF
source "$ROBOTICS_OUT/install/local_setup.bash"
```

上例 `OFF` 只构建厂家接口和通用串口库，不生成硬件 UWB 驱动。实机需要驱动时，在 ARM64 上核对厂商静态库和串口配置后使用 `-DBUILD_UWB_VENDOR_DRIVER=ON` 重新构建；仅编译不会启动串口设备。

### 导航、启动包与点位包

- `behavior_ext_plugins` 是 C++ Nav2 插件，需要 Nav2 开发包和 BehaviorTree.CPP v3；只存在 `nav2_msgs` 不够。
- `robot_slam_bringup` 是 Python 启动包。它的 package.xml 声明了 RealSense、Nav2、STVL、`go2_description`、`vins` 等运行依赖。能够安装 launch 文件不代表这些节点和插件都能启动；各入口按自己的依赖准备。
- `waypoint_nav` 需要可导入的 `marsdog_voice_interaction.srv.VoiceTask`，接口来源是 `modules/voice`。如果已有本机原生安装，先加载其安装前缀；没有时按总仓库 Voice 构建流程生成接口，不要单独复制 srv 文件充当安装。
- 加载新的 `out/rk3588-navigation/use-navigation.sh` 后，Nav2、MPPI、STVL、GO2 描述及相关自有包已可发现；只加载旧 RTAB-Map 环境不会自动加载导航 overlay。`vins` 本次跳过，VINS-Fusion 入口仍需单独补齐。

依赖备齐后，可沿用第一段构建命令，将 `--packages-select` 后的包名替换成需要的包。一次选择全部 9 个包之前应先确认这些额外依赖；不要对整个总仓库递归 `colcon build`，避免发现外部仓库、旧产物或重复包。

## 修改源码与增量编译

继续使用同一 `--base-paths`、`--build-base`、`--install-base` 和架构。修改一个包时选择该包；修改 Action/srv、导出头文件或库时，同时重新构建依赖它的自有包。例如变更 UWB 接口后至少检查 `go2_uwb_local_follow`、`go2_uwb_behavior` 及外部调用方。

`--symlink-install` 便于 Python、launch 和配置开发；C++、生成接口仍需编译。最终以 install 下实际文件为准，修改后重新加载环境并重启自己启动的节点。不要复用 WSL/x86_64 的 build 目录进行板端 ARM64 构建。

## 验证范围

总仓库基础检查：

```bash
cd "$MARS_ROOT"
python3 -B tools/dev.py check
```

已构建包的测试使用同一输出目录，例如：

```bash
colcon --log-base "$ROBOTICS_OUT/log" test \
  --build-base "$ROBOTICS_OUT/build" \
  --install-base "$ROBOTICS_OUT/install" \
  --packages-select person_3d_localization
colcon test-result --test-result-base "$ROBOTICS_OUT/build" --verbose
```

launch 测试和硬件测试需先阅读测试内容，避免与运行中的底盘或 ROS 图竞争。总仓库 `tools/check_robotics.py` 是无硬件构建/验收工具；其选择的包不覆盖全部 9 个包，更不等于 D435i 建图、Nav2 运动或串口设备已验收。

加载后可用 `ros2 pkg prefix <包名>` 核对实际版本和安装目录。OpenVINS、RTAB-Map 的源码修改与独立复现流程仍见 `out/rk3588-slam-features` 和 Windows `D:\work\doc` 中的 SLAM 编译文档。

## 三机器人统一导航配置

Lite3、GO2 和宇泛灵猫现在统一使用 `robot_slam_bringup/nav.launch.py`，通过 `robot:=lite3|go2|lingmao` 选择配置，共用 MPPI、STVL、Smac Hybrid 和 Constrained Smoother。未指定 robot 时保留 Lite3 默认参数。详见 [三机器人配置与切换指南](ROBOT_PROFILES.md)。


## 灵猫官方通信桥接

外置 RK3588 与灵猫的有线网络、官方 ROS 2 bridge/client 和观测接入见 [灵猫通信指南](LINGMAO_COMMUNICATION.md)。导航继续使用 `nav.launch.py robot:=lingmao`。当前旧版固件的 DHCP、实际只读 RPC、机器人 IMU 和电池通信已通过；用户已确认站立操作后 /odom 恢复。D435i 双目接收已检查，相机 IMU 的 HID/IIO 支持与完整导航仍待验收。
