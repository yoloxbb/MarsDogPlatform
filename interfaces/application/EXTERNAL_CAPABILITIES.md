# 外部执行能力边界

当前没有运控算法、嵌入式或 BMS 仓库。本文件登记已有调用边界，不定义其内部实现。

| 能力 | 当前代码依据 | 边界 |
| --- | --- | --- |
| Lite3 命令/速度/状态 | modules/action/marsdog_action_executor/adapters/lite3_backend.py 内 make_ros2_lite3_backend / Ros2Lite3StatusSubscriber | 现有 simple command、Twist、RobotStatus 适配；实际 transfer_interfaces 来自外部，生产兼容性 UNKNOWN |
| Go2 | modules/action/marsdog_action_executor/adapters 内 Go2 实现 | unitree_api / unitree_go，保留现有协议；非本机 Lite3 profile |
| 导航 | waypoint_nav_dispatcher.py、Action waypoint_nav_adapter.py | 固定 VoiceTask JSON 与 Nav2 NavigateToPose；取消接受不等于终止 |
| 跟随/局部避障 | go2_uwb_behavior、go2_uwb_local_follow | 保留既有 ROS action、话题、超时与停止路径；名称含 go2 不代表更换为新协议 |
| 电池观测 | BATTERY_OBSERVATION.md | 只有新鲜且明确非模拟的观测可用于 Energy 结算；当前无真实生产者 |

外部执行器返回事实，由 Action 管理阶段和终态；BT 不导入厂商实现。
新设备适配仍位于 Action 的能力边界，先验证现有调用需求，不创设未提供的控制报文。

开发用 simulated_lite3.py 只在显式本机 profile 下运行。它模拟状态/确认，
将输出标成 simulated 并发布到 /development/lite3_io，不发布硬件命令或电池证据。
它不能用于验证控制精度、动力学、急停、充电或硬件安全。

生产切换需要设备侧提供：实际 IDL/SDK 版本、端点/坐标系/单位、状态来源、控制权和停止确认、
部署命令及实机回放。收到资料后做适配与验收，不预设其内部算法。
