# Lite3 本机真实 Nav2 验收

本配置为既有 lite3-local-cpu 的可选扩展，不改变默认入口或机器人生产参数。
Ubuntu 22.04 / ROS Humble / x86_64；ROS domain 212，loopback Cyclone DDS。

在 WSL 主仓 /home/elephant/MarsDog/marsdog-platform 中：

~~~bash
python3 tools/marsdog.py up --profile lite3-nav2-cpu
python3 tools/marsdog.py smoke --profile lite3-nav2-cpu
python3 tools/check_nav2_recovery.py
python3 tools/check_local_lifecycle.py --profile lite3-nav2-cpu
python3 tools/check_action_shutdown.py
~~~

Ctrl-C 关闭整组进程。运行证据在 out/nav2-local/runs，故障契约在
out/nav2-recovery/runs；同一 profile 共用锁，不能同时启动这两种验收。
默认 python3 tools/marsdog.py up 仍运行此前的 lite3-local-cpu。

## 实际运行范围

~~~text
Voice mock → audio_event → BehaviorTree → ExecuteBehavior → Action
  → waypoint_nav/VoiceTask → Nav2 NavigateToPose
  → Navfn 规划器 + Regulated Pure Pursuit 控制器
  → /development/nav2/cmd_vel → 理想二维运动积分 → /odom + TF
~~~

Nav2 navigator、planner、controller、costmap 和 lifecycle manager 是固定版本
Humble 二进制；自研 behavior_ext_plugins 从原代码构建，在真实 behavior_server
中加载和激活。该插件没有在此验收中执行脱困动作，不能据此声称其脱困算法已验收。
定位、地图、运动反馈、相机和语音输入是明确的模拟输入；没有运行相机 SLAM、
真实模型推理、Lite3 运控、嵌入式或 BMS。没有把模拟电量用于 Needs 结算。

参数与 XML 位于 config/nav2，属于本机测试配置。测试地图包含墙体；
航点 C 位于墙内，用于不可达测试；A/E 用于成功与绕障测试。
这份地图和参数不是机器人部署配置。Nav2 的局部 BT 只编排路径规划/跟踪；
MarsDog BehaviorTree 继续负责全局行为选择与抢占，Action 继续负责技能执行阶段。

## 验证

整链路 smoke 必须观察到关联的 GO_HOME 成功、实际 /plan、非零速度输出、
位姿变化和 Nav2 成功终态。默认硬件话题没有发布者。

7 项故障契约通过公开 ROS 服务/话题验收：

1. Nav2 实际规划并到达 A。
2. cancel 在 Nav2 确认真正终止后才报告 INTERRUPTED。
3. 超时发起取消，收到 Nav2 终态才报告 TIMEOUT。
4. 墙内航点失败，不能误报到达。
5. 暂停本次运行的 navigator 后进入 RECOVERY_REQUIRED，新目标返回
   RECOVERY_BLOCKED；恢复进程后等待真实终态才释放锁。
6. 锁释放后规划绕墙路径并到达 E，并验证模拟执行轨迹的机器人半径不穿墙。
7. 之前成功任务的终态仍可查询。

通信中断测试暂时冻结理想运动输入，仅向本轮进程清单中的 navigator 发 SIGSTOP/
SIGCONT；finally 恢复进程。测试缩短 waypoint 的取消确认时间为 1 秒，生产默认不改。
测试不调用 release_recovery，也不伪造操作员停止确认。

进程门禁额外检查 SIGTERM、重复启动拒绝、Action 子进程崩溃导致整组失败退出，
以及所有自有 PID 被回收。
关闭时先停止上层请求，再调用 Nav2 现有 ManageLifecycleNodes.SHUTDOWN，
确认生命周期结束后才退出进程。首次同时发送 SIGINT 暴露过反馈发布器在 context
失效后的异常退出；失败记录保留，未把非零退出放宽为通过。

## 环境与构建

~~~bash
python3 tools/marsdog.py prepare --profile lite3-nav2-cpu \
  --uv /home/elephant/MarsDog/migration/.tools/uv \
  --archive-dir /home/elephant/MarsDog/migration/archives
python3 tools/marsdog.py build --profile lite3-nav2-cpu
python3 tools/marsdog.py doctor --profile lite3-nav2-cpu
~~~

扩展依赖固定于 third_party/extended-ros-deps.lock.json。
prepare_extended_ros.py 校验下载 SHA256，提取到 out/extended-ros/deps；
它不运行 apt install、不更新系统包。Debian CMake/pc 中的绝对路径在单独的
out/extended-ros/relocated 副本中适配；原包提取字节不改。每项适配记录在
relocations.json；再次 prepare 会从包重建预期清单，拒绝被修改的现有内容。

有些开发库的相对链接依赖已安装的系统运行库；适配副本显式链接该主机库，
所以这不是完整容器镜像。原有系统依赖清单记录在验收证据；换主机必须重新 build/
doctor/smoke。ROS、系统 OpenCV 4.5.4 与 Python Vision 环境仍分开。

## 固定 SLAM 源码构建

~~~bash
python3 tools/materialize_vendors.py --only openvins rtabmap \
  --archive-dir /home/elephant/MarsDog/migration/archives
python3 tools/prepare_extended_ros.py
python3 tools/check_extended_ros_build.py nav2-plugin openvins rtabmap
python3 tools/check_extended_ros_runtime.py
~~~

OpenVINS 使用原固定 fork，RTAB-Map 核心与全部 ROS wrapper 仍来自固定外部快照；
不把供应商代码迁为自研包。构建结果在 out/extended-ros。
RTAB-Map 的现有 rtabmap_util 依赖 GUI 库，故保留 Qt 构建。
核心的上游 CMake 会生成 DatabaseSchema.sql，因此只在 out/extended-ros/vendor-source
中的核心得到编译；固定 .external 快照和只读 ROS wrapper 源码仍须通过原始 Git 树校验。
是否支持 GTSAM/g2o 等可选后端必须读取实际构建特性记录，不能仅由开关推断。

构建、ELF 依赖解析、原有单元测试与真实传感器定位精度是不同验收层。
本机图像/IMU标定与设备输入尚未提供，不能声称整机 SLAM/建图/避障性能已通过。

最终本机记录：OpenVINS 4 包、RTAB 核心及 wrapper 16 包构建通过；
原有 test_leg_velocity 1 项通过，100 个 ELF 依赖解析通过。RTAB 核心 0.23.8 与
wrapper 0.23.7 保持原 fork；g2o/GTSAM/Ceres 优化后端未启用，Torch/CudaSift 关闭。
Action 的同类退出竞态已修复，SIGINT/SIGTERM 均验证先发布模拟停止再退出；
原有取消/drain/停止语义不变。冻结证据见 validation/real-nav2。
