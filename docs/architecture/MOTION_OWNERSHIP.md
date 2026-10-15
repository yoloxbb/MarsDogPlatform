# 应用运动控制权

Action 是应用行为的唯一执行入口。BT 的直驱与内部候选共用仲裁；导航、跟随和靠近
都作为 Action 的阶段或长期任务执行。应用层所有权不替代底盘急停与设备停止反馈。

## 一次 Goal 的生命周期

`on_goal` 在原预留锁下取得 `MotionLease(goal_id, generation)`；已有 Goal 或控制器
未决时拒绝新 Goal。`on_accepted` 将 lease 绑定到实际 goal_handle；`on_execute`
检查同一代所有权，取消/急停已撤销执行权时不启动计划。

普通取消和长期 Goal 的上游租约失效继续调用现有控制器停止路径；取消 ACK 不释放
执行权。最终清理完成后 `finish` 才结束本次应用 lease；下游未决时另存恢复阻断。
即使复用 goal_id，旧 handle 的取消和旧 generation 的终态也不能影响新执行。

统一检查 UWB follow/roam、三维靠近、人物靠近、局部运动、航点及其他已注册适配器。
局部运动的 `active` 在真实终态和底盘停止确认前保留；航点的 `navigation_interlocked`
在查询/取消结果未决时保留。属性读取失败按状态未知处理。

执行异常请求已有停止出口；清理异常仍释放 Python 锁，但留下恢复阻断，拒绝下一次
运动。明确的控制器恢复由原有恢复机制负责；不能把故障清理完成当作已停止。
`operator_recovery_required` 的未知清理/执行故障不会由空闲检查自动抹除，需操作人员
确认控制器及设备状态后按既有停机恢复流程重新启动应用。

## 当前指令来源与责任

| 来源 | 输出边界 | 应用交接条件 |
| --- | --- | --- |
| Action 的 Lite3 速度/姿态 | 现有 `/cmd_vel`、`/simple_cmd` | 当前应用 Goal；原姿态、电量、障碍物、代理动作门限 |
| 视觉靠近、转向与局部运动桥 | Action 适配器和底盘 backend | 同一 Goal；局部命令还检查时间戳、0.2 秒新鲜度、deadline |
| waypoint / 地图靠近 | Nav2 执行端 | 请求属于当前 Goal；Cancel ACK 后等 Result；未知终态保持恢复锁 |
| UWB follow / roam | go2_uwb_behavior → 底盘 | 跟随链获得授权后执行；空闲不持续发布速度；停止确认后交接 |
| robot_local_motion | planner → task server → Action bridge | 限定 movement unit、显式模式与目标；过期输出归零并取消 |

实现是受管应用链路的约束，不是 `/cmd_vel` 的全系统硬件多路复用器。
额外启动的 teleop、调试节点、第三方直接发布者不受 Action 的 Python 锁管理。
生产部署必须按选定 profile 核对这些来源，保留 Lite3 冲突检测、UWB 空闲静默、
Nav2 取消终态及本机已有底盘看门狗；不能据应用单测宣称任意外部发布者已被拦截。
实机停止距离、模式切换、断网和进程重启仍需指定设备验收。

## 回归依据

- `test_motion_ownership.py`：并发接收仅一个所有者、同 ID 不同代隔离、迟到取消、
  全部恢复阻断、取消前不启动、执行/清理异常。
- 原长期 Goal、局部运动、靠近、航点 DDS 和 SIGINT/SIGTERM 停止测试继续执行。
- 既有设备报文、ROS 类型、优先级元组与需求结算规则不变。
