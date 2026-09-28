# Action 长期 Goal 修改需求

Tree 已将 `follow_owner` 和 `play_alone` 设为 `lifecycle_scope=behavior`、
`completion_policy=until_preempted`、`cancel_on_voice_idle=false`，并向
`/execute_behavior` 发送 `timeout_sec=0`。`interaction_id` 仅用于来源关联，
Goal 的独立身份是 `behavior_id`/`goal_id`。语音 idle 会关闭会话级
`/behavior/attention_tracking`，不取消这两个行为。当前 Action 尚不兼容这份
长期 Goal 契约；部署前须完成以下修改。

## 1. 外层超时与结果

- `timeout_sec <= 0` 表示外层 `runtime_deadline=None`，一直运行到取消、
  控制器失败或关机。当前 `ros_node.py` 把 `0` 加到启动时间上，会立即到期。
- 有界行为的超时语义保持不变。内部 UWB 请求、导航、目标丢失、状态失鲜和
  控制器健康检查继续使用有限超时；不能把内部超时也设成无限。
- 长期 Goal 必须持续发布 Feedback，包括当前阶段、周期和
  `safe_to_interrupt`。失败时返回真实 FAILED Result；取消时停车后返回真实
  CANCELED Result。取消受理只代表 `CANCEL_REQUESTED`。

## 2. `follow_owner`

- 将当前“短期确认 Goal + 会话级后台 UWB 跟随”合并为**一个**长期
  `follow_owner` Goal。Tree 不再通过 attention 通道发送跟随启用指令
  （`enabled=true`、`mode=follow_owner`）。
- Go2 外部 UWB 进程链和 Lite3 `/go2/follow_uwb` 各自只能由该 Goal
  启动一次。Goal 在跟随时保持 RUNNING，持续检查进程/服务、目标失联和
  控制器状态，不能每隔数秒由 Tree 重复下发。
- CancelGoal、显式停止、急停、失败及节点退出均须停止 UWB 和底盘输出。
  Lite3 必须等待内层跟随 Action 的真实终态；Go2 必须确认外部进程退出和
  底盘停车。原会话跟随优先级门在 Goal 完全纳入 Tree 仲裁后应移除或收敛，
  避免双重仲裁。抢占后默认不自动恢复。

## 3. `play_alone`

- Lite3 保留现有 `/go2/random_roam` 链路，在**同一个** Behavior Goal 内
  循环“RandomRoam → 成功 Result → 确认停稳 → 随机玩耍姿态 → 周期 Feedback”。
  不通过 waypoint `K`、直接 `/cmd_vel` 或重复 Tree Goal 实现循环。
- 每次漫游和姿态仍有各自有限预算；漫游拒绝、业务码非 SUCCESS、目标丢失、
  停稳失败或姿态失败应结束外层 Goal 并报告失败，不得盲目开始下一周期。
- CancelGoal 必须取消当前内层漫游、等待真实终态、停稳并停止底盘，再返回
  外层 CANCELED。取消受理或内层终态未知时不得释放底盘所有权。

## 4. 仲裁和验收

- 旧 Goal 从 RUNNING 到 CANCEL_REQUESTED 后，继续持有运动控制权；只有
  真实终态到达，Tree 才会启动替代 Goal。Action 仍须保持单一 `/cmd_vel`
  所有者。Lv0 急停和 Lv1 视觉安全事件可抢占这两个长期行为。
- Tree 正常退出会尝试请求取消当前 Goal，但当前退出路径不等待真实 Result；
  进程被强制杀死时甚至无法发送取消。
  Action 需明确处理长期 Goal 的上游失联，例如有界租约/心跳；若采用租约，
  还须与 Tree 增加续租契约。不能假设 ROS Action Client 断开就会自动停车。
- 软件回归至少覆盖：语音 idle 不停车；同名事件不产生重复 Goal；安全事件
  取消旧 Goal 后等待真实 Result；漫游成功后重复完整周期；失败/目标丢失/
  节点退出可靠停车；取消受理但 Result 未到时拒绝替代 Goal。
- 软件测试不能代替真机验收。部署时需重建、重新 source 并重启 Tree 和
  Action，再核查 UWB、控制器反馈与 `/cmd_vel` 发布者。
