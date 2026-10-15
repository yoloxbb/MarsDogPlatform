# 公共接口迁移（2026-10-15）

用户明确批准不兼容迁移，不提供旧端点别名、双入口或旧类型回退。
这是当前公共约定的一次实施记录；命名约定仍以 AGENT_DEVELOPMENT_CONVENTIONS.md 为唯一公共说明。

| 原接口 | 当前唯一接口 | ROS 类型 |
| --- | --- | --- |
| /execute_behavior | /action/execute_behavior | marsdog_interfaces/action/ExecuteBehavior |
| /waypoint_nav/task、/waypoint_nav/navigation_task | /navigation/task | marsdog_interfaces/srv/NavigationTask |
| /waypoint_nav/status | /navigation/status | std_msgs/msg/String |
| /waypoint_nav/markers | /navigation/markers | visualization_msgs/msg/MarkerArray |
| /go2/follow_uwb | /motion/follow_uwb | go2_uwb_behavior/action/FollowUwb |
| /go2/random_roam | /motion/random_roam | go2_uwb_behavior/action/RandomRoam |
| /go2/orbit_uwb_once | /motion/orbit_uwb_once | go2_uwb_behavior/action/OrbitUwbOnce |
| /go2/set_behavior | /motion/set_behavior | go2_uwb_behavior/srv/SetBehavior |
| /go2/behavior_diagnostics | /motion/behavior_diagnostics | diagnostic_msgs/msg/DiagnosticArray |
| /go2/random_roam/target、play_center | /motion/random_roam/target、play_center | geometry_msgs/msg/PoseStamped |

ROS 2 约束名称语法，不规定这些业务路径。上述路径由 MarsDog 的接口登记表规定。
现有 FastAPI /api/v1 资源路径、Nav2 的 /navigate_to_pose 与 /spin、TF 坐标系及 SLAM 外部接口沿用现有契约。
包名、节点名及文件名保留准确的组件职责名称；没有强制所有节点增加 _node 后缀。
VoiceTask 与 VisionTask 仍是各自感知领域的 ROS 类型。

## 实现与运行行为

NavigationTask 是航点的唯一 ROS 类型，Action 与 waypoint_nav 均删除对 Voice 包的依赖。
删除 enable_navigation_task、enable_legacy_voice_task、waypoint_nav_task_interface 参数及迁移配置。
ExecuteBehavior 仅由 marsdog_interfaces 生成；删除 Action 包内重复 IDL、生成代码和消费者的旧包回退。
ROS 模式的 Behavior 在公共类型缺失时启动报错，避免误退回模拟执行器；无 ROS 的显式软件测试仍可运行。
调试主题统一使用 /debug/execute_behavior/*，删除旧别名及 MARSDOG_LEGACY_DEBUG_TOPICS 开关。

同步修改服务端、Action/Behavior 客户端、默认配置、launch、检查工具、测试、接口登记与当前文档。
IDL 的字段、任务 JSON、业务事件/行为/Unit ID、导航取消真值、持久化任务 ID 和恢复锁语义保持一致。
不调整运动阈值、地点映射、算法或模型。
历史迁移基线和原仓记录保留。受保护配置只允许 integration/naming/interface_migration.json 记录的精确名称替换，检查时逆向还原后继续校验原基线。

## 验证与切换

构建和真实 DDS 测试入口：

```bash
python3 tools/dev.py check
python3 tools/dev.py test action
python3 tools/dev.py test behavior
bash tools/check_navigation_slice.sh --output out/navigation-interfaces --underlay out/local/ros/install
```

最后一项在独立 overlay 编译公共接口、Action、waypoint_nav、UWB 服务，使用 domain 213、localhost、临时任务库和假 Nav2，检查取消、持久化、重启恢复及 UWB Action 通信。它不连接硬件。
底层 ROS 依赖需要预先安装；不自动升级或下载运行库。

实际部署必须停止旧版本相关服务，同时切换上述生产消费方和配置，并从空构建目录重建受影响包。
旧版 Action 包残留的生成类型不能带入新安装。运行时只加载新 overlay，确认新端点和类型后再恢复业务。
不要用删除任务数据库解除锁；未决导航仍需按恢复协议处理。
回滚需整体恢复同一版本的源代码、安装和配置，保留 ~/.ros/waypoint_nav.sqlite3 及数据。
本次源码修改与隔离测试不等于运行中的设备服务已经切换或实机验收。
