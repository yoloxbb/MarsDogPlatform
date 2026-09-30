# 导航与避障负责人交接

本交接以五模块兼容性重构完成后的主仓为基线。导航/避障的内部修改由其负责人继续；
本轮仅整理已有边界，没有改导航算法、航点配置、IDL、锁文件或运动门限。
唯一开发仓是 marsdog-platform，不回旧仓重复实现。真实负责人账号仍待团队提供。

## 入口与职责

| 范围 | 当前入口 | 谁决定什么 |
| --- | --- | --- |
| 行为决策 | modules/behavior/marsdog_behavior | BT 选择目标、仲裁和请求抢占，不直接操作 Nav2 |
| 动作与导航适配 | modules/action/marsdog_action_executor/adapters/waypoint_nav_adapter.py；config/navigation_waypoints.yaml | Action 负责阶段、Goal 归属、外部能力反馈和行为终态 |
| 航点服务 | robotics/ros2/src/waypoint_nav | 地点解析、Nav2 Goal 生命周期、持久化、查询与恢复锁 |
| UWB / 局部跟随避障 | robotics/ros2/src/go2_uwb_behavior、go2_uwb_local_follow | 保留原有 action/topic、超时和停止接口；包名中的 go2 不代表本轮改为另一设备协议 |
| 公共登记 | interfaces/registry.json；interfaces/application/EXTERNAL_CAPABILITIES.md | 公开端点和类型；不提供未拿到的嵌入式内部实现 |

航点详细依据是 [原接口及置顶修订](../../robotics/ros2/src/waypoint_nav/docs/INTERFACE.md)。
其置顶的 operator recovery amendment 优先于后面的旧说明：
普通 cancel 不能解除 RECOVERY_REQUIRED。需要改协议时，Action 消费端与航点服务一起
评审和验证；不得为了消除依赖而直接重命名历史 ROS 类型。

## 公开协议与关键约束

| 端点 | 类型 | 约束 |
| --- | --- | --- |
| /execute_behavior | marsdog_interfaces/action/ExecuteBehavior | BT→Action；取消接受不等于旧 Goal 已终止 |
| /waypoint_nav/task | marsdog_voice_interaction/srv/VoiceTask | 历史类型复用必须保留；不是视觉 VisionTask，也不是语音任务语义 |
| /waypoint_nav/status | std_msgs/msg/String JSON | 先持久化后发布；Topic 不重放，丢消息通过 query 补偿 |
| /waypoint_nav/markers | visualization_msgs/msg/MarkerArray | 可视化，不是完成证据 |
| /navigate_to_pose | nav2_msgs/action/NavigateToPose | 航点服务→Nav2；真实终态决定导航是否结束 |

所有航点 params_json 都是 object，包含 protocol_version="1.0" 和
client_id="marsdog_action_executor"。task_id 为 1–128 位字母/数字/._:-；
请求响应回显 task_id/task_type。取消、查询使用新请求 ID，另带 target_task_id。
latency_ms 是 service 处理时间，不是导航耗时。

goto_place 的 place 使用稳定 ID 或精确地点名称，只去首尾空白；不做模糊意图解析。
v1 preempt 必须为 false。timeout_sec 从 QUEUED 落盘开始，不含到点后的动作阶段。
terminal_retention_sec 不小于 86400。重复任务不得再次运动，终态详情过期也保留
task ID tombstone，不能复用为新任务。

success=true / accepted=true 只表示受理，不能上报到达。
状态可能早于 service 回复，先按 task_id 关联，再按响应或 query 的 matched_id 校验；
不能把中文 place 与 matched_id 直接比较。sequence 对同一任务递增，旧状态不能回退
当前状态。查询接口本身 success=true 也不保证目标存在，必须读取查询结果。

## 取消、终态与重启恢复

| 观察 | 调用方应保留的行为 |
| --- | --- |
| QUEUED | 只有可原子撤回时 safe_to_interrupt=true |
| DISPATCHED | Nav2 是否收到未知；不能认为停止，不能启动替代导航 |
| NAV2_ACCEPTED | 可定向取消且尚未请求取消时才可抢占 |
| cancel ACK / timeout / 服务暂时不可达 | 继续持有旧 Goal 归属与执行锁，查询等待确认；不合成成功/停止 |
| SUCCEEDED / NAV2_SUCCEEDED | 确认到达后，Action 才能进入既有后续 Stage |
| FAILED / GOAL_REJECTED、NAV2_FAILED、INTERNAL_ERROR、TIMEOUT | 依原条件确认失败；TIMEOUT 也不能绕过停止确认 |
| INTERRUPTED / CLIENT_CANCELLED、NAV2_CANCELED | 已确认取消或 QUEUED 原子撤回；不是成功结算 |
| RECOVERY_REQUIRED | 未知 Nav2 状态，阻止新导航；普通 cancel 仅记录意图，不释放锁 |
| INTERRUPTED / RECOVERY_RELEASED | 显式人工解除后的中断；不是到达、不是 Nav2 确认取消 |

服务重启时，持久化 QUEUED 证明尚未发 Goal，可记录失败；
其他未决阶段保持恢复锁，用保存的 UUID 查询 GetResult/CancelGoal。
STATUS_UNKNOWN 不是停止证据。默认存储 ~/.ros/waypoint_nav.sqlite3 使用 SQLite/WAL；
测试必须使用独立数据库，不能清空生产任务库“解锁”。

release_recovery 只供操作人员在确认机器人已停止后使用：
除通用字段和 target_task_id 外，需要 JSON 布尔 operator_confirmed_stopped=true。
缺失、false 或非布尔值返回 OPERATOR_CONFIRMATION_REQUIRED；
非恢复状态返回 NOT_IN_RECOVERY。该字段是人工声明，不是认证或物理停止检测。
自动客户端不得生成此操作。本页不提供自动调用脚本。
成功必须先持久化 INTERRUPTED/RECOVERY_RELEASED 再解锁，
部署时同时使用能识别此代码的当前 Action；历史 Action 版本可能拒绝它。

## 当前配置需要特别核对

- Action 生产 navigation_waypoints.yaml 的 enabled 仍是 false；本机生成配置单独开启。
- 当前 Action 语义映射为 A=卧室、B=充电桩、C=厨房、D=卫生间、E=客厅。
  航点网页的缺省名称示例与此不同，接入真实地点文件时必须核对，不能按示例覆盖。
- 服务默认期限：service 5 秒、query 2 秒、取消确认 5 秒、抢占锁等待 8 秒，
  终态保留 86400 秒。超时不是许可释放锁。
- 服务支持保留随机目标 K / "11"，都归一为 matched_id="11"；
  但 Action 当前 random_navigation_fixed_pool=[A,B,C,D,E] 生效，
  随机行为实际在固定池中选点。不要顺手清空这个原有覆盖项。
- Action 的旧直接 Nav2 配置仍用于兼容/测试注入；生产固定/随机路由走航点服务。
- 默认 lite3-local-cpu 使用模拟 Nav2；lite3-nav2-cpu 才运行真实 Nav2，
  其地图/里程计/TF/运动仍为模拟，速度重映射到 /development/nav2/cmd_vel。
- 五模块重构没有改变跟随/局部避障或 Lite3 SDK。设备的 IDL、坐标系、单位、
  控制权及停止反馈需要设备资料，不从 mock 成功推定实机兼容。

## 接手后的验证顺序

先读 AGENTS.md 和 [开发流程](WORKFLOW.md)，记录 git status，保留未提交改动。
用下列入口复现默认软件基线，再根据实际导航改动增加门禁：

~~~bash
python3 -B tools/dev.py check
python3 -B tools/dev.py test action
python3 -B tools/dev.py test behavior
python3 -B tools/check_contracts.py
python3 -B tools/check_action_transport.py
python3 -B tools/marsdog.py doctor
python3 -B tools/marsdog.py smoke
~~~

前提是按 QUICKSTART 准备各环境并 build；Action 单测中的 ROS/GUI skip 不当作通过。
航点侧必须保留原 tests 及 Action tests/test_waypoint_nav_adapter.py 的以下覆盖：
状态早于 ACK、重复 ID、漏终态 query、未知状态拒绝、服务故障不解锁、
取消与到达竞态、显式人工恢复是中断且不结算成功。

涉及 Nav2/航点修改时，在专用本机环境按 [Nav2 组合](../LOCAL_NAV2_CPU.md)
准备扩展依赖，再执行 smoke --profile lite3-nav2-cpu、
check_nav2_recovery.py、check_local_lifecycle.py --profile lite3-nav2-cpu。
涉及原生跟随避障/C++ 时运行 check_robotics.py 或对应 CMake/CTest。
导航内部此次未变，已有真实 Nav2 故障证据保留在 validation/real-nav2，
本轮不会把历史通过写成重新运行或实机验收。

负责人最终需要提供：修改范围和兼容性影响、接口与超时/取消/终态测试、
板端系统/ABI/ROS/RMW/SDK、地图/定位/传感器输入来源、实际停止确认和设备回放。
这些事实到位后再形成板端配置和实机验收记录；当前交接无需改五模块的领域权威。
