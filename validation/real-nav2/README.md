# 真实 Nav2 / SLAM CPU 增量验收

日期：2026-09-29。源码提交见 release-manifest.json。运行在 WSL Ubuntu 22.04、
ROS Humble / Python 3.10 / x86_64。所有测试仅限本机隔离 ROS 域，进程已关闭。

- nav2-smoke/runtime：真实 Voice(mock) → BT → Action → waypoint → Nav2；
  实际规划/速度/模拟运动反馈与关联成功终态；全部退出码为 0。
- navigation-recovery：7 项真实 ROS 故障契约；绕墙执行轨迹最小距离约 0.280 m，
  测试机器人半径 0.15 m。这是静态地图和理想运动验证，不代表物理碰撞检测。
- 两套 lifecycle：中断、重复启动拒绝、崩溃传播；child_crash 观察到 FAIL 是预期。
- action-shutdown：SIGINT/SIGTERM 发出模拟停止后正常退出；Action 回归 423 pass /
  29 skip。action-wheel 验证独立非 editable 安装与维护源文件一致。
- contracts：25 项已有检查通过；architecture：15 ROS manifests、21 接口。
- builds：Nav2 自研插件 1 包、OpenVINS 4 包、RTAB 核心与 wrappers 16 包构建通过。
  OpenVINS 原有 CTest 1 项通过，extended-runtime 的 100 个 ELF 依赖解析通过。
- 6 项隔离准备工具测试通过；vendor、原仓及系统包清单校验通过。
- historical-failures 保留退出竞态的实际失败；其他早期依赖/路径失败保留在 out，
  SHA256 与位置在 historical-failures.json。它们不是已接受结果。

未验收：实际模型推理、传感器标定/定位精度/SLAM 性能、Lite3 设备控制与停止、
BMS/充电/对接、动态物理障碍、Nav2 脱困算法、生产参数、远端 CI、二进制对外分发。
RTAB 可选功能以 extended-runtime.json 的真实构建输出为准；未启用的后端不算通过。
测试数有不同层次，不跨报告相加。旧 validation/local-platform 快照保留原字节。

复现命令及依赖准备见 ../../docs/LOCAL_NAV2_CPU.md。
