# P6 可选真实 Nav2 与完整 ROS CPU 构建

2026-09-29。Lite3 本机 CPU 的增量阶段已完成软件验收。没有再次搬代码、改变公开
IDL、修改算法、合并 Python 环境或推测硬件协议。

| 验收项 | 实际结果 | 证据（validation/real-nav2 下） |
| --- | --- | --- |
| Voice → BT → Action → waypoint → 实际 Nav2 | 15 个服务进程 + probe，关联 GO_HOME 成功；实际路径、速度、位姿、导航终态 | nav2-smoke.json、nav2-runtime.json |
| 导航故障与恢复 | 7 项通过，包括取消、超时、不可达、失联锁定、恢复绕墙、旧终态查询 | navigation-recovery.json |
| 两套 profile 生命周期 | 中断、重复启动拒绝、子进程故障传播、自有 PID 回收通过 | nav2-lifecycle.json、baseline-lifecycle.json |
| Action 退出 | SIGINT / SIGTERM 均先发出模拟停止命令再退出，exit 0 | action-shutdown.json |
| Action 独立回归 | 423 pass / 29 skip | action.xml |
| 已有跨进程契约与基线 | 25 pass；15 ROS manifest DAG、21 登记接口 | contracts.xml、architecture.json |
| 自研 behavior_ext_plugins | 原码构建成功，并在真实 Nav2 behavior_server 加载/激活；未执行脱困算法验收 | builds/nav2-plugin-build.json |
| 固定 OpenVINS | 4 包构建；原有 test_leg_velocity 通过 | builds/openvins-build.json、openvins-tests.xml |
| 固定 RTAB-Map | 核心 + 全部 ROS wrapper，共 16 包构建通过 | builds/rtabmap-build.json、rtabmap-package-inventory.json |
| 扩展 ELF 加载依赖 | 100 个 ELF 文件解析通过；不代表传感器算法验收 | extended-runtime.json |
| 构建隔离工具 | 6 项路径、幂等、污染与篡改拒绝测试通过 | preparation-tests.txt |
| 原始数据保留 | 原始七仓、OpenVINS 329 文件、RTAB 1738 文件通过校验；系统包清单未变 | original-sources.json、vendor-verification.txt、host-unchanged.json |

平台通过公开接口组合真实 Nav2，没有给 BT、Action、waypoint 增加私有跨模块 import。
唯一业务源码修复在 Action 的 main：禁用 rclpy 自动信号关闭 context，先完成已有
取消/停止流程再显式关闭。原有 7 秒 drain、终态语义、默认配置和机器人协议均保留。
这项修复同时适用于两套 profile；详见 P3_ACTION.md。

可选 profile 另使用 Nav2 现有 ManageLifecycleNodes.SHUTDOWN：先停止上层请求、
等待 Action 释放目标，再结束 Nav2 生命周期。首次同时 SIGINT 暴露过反馈发布器/
context 竞态；失败证据保留，非零退出仍判失败。

73 个固定 Debian 包只提取到 out。原始包字节不改，绝对路径适配发生在可重建的
派生 CMake/pc 视图中。系统 dpkg 清单完全不变；这不是完整部署镜像。
RTAB 上游 CMake 会在源树生成 DatabaseSchema.sql，因此核心在独立构建副本编译。
已恢复并校验固定 .external 快照；生成物保存在 out，未加入第三方源快照。

RTAB 核心 0.23.8 / ROS wrapper 0.23.7 来自原固定 fork，未升级。实际构建启用了
OpenVINS、Qt/VTK、OctoMap；没有 g2o/GTSAM/Ceres 优化后端，Torch/CudaSift 关闭。
具体特性及上游输出的许可标签保留在 extended-runtime.json，不据此批准对外分发。

旧 profile 仍是 lite3-local-cpu。新入口和复现方式见 ../LOCAL_NAV2_CPU.md。
冻结证据 manifest 记录源码提交及哈希；旧 validation/local-platform 报告保持原样。

下一阶段：已有 CPU 适配基础上接入实际视觉/语音模型与录音/图像回放。
需要真实模型资产和可用测试数据；传感器标定、Lite3 外部接口与设备、厂商分发许可、
远端和 owner 绑定仍是后续门禁。本轮结果不能替代实机性能或完整产品验收。
