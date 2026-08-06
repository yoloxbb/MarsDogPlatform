# 行为树项目交接说明

> 对接基线：2026-08-04 / 多项目契约 1.0.0

## 1. 本项目负责什么

行为树是四项目的决策中心：接收语音、视觉、情绪和内部需求，把事件映射为语义 `behavior_name`，通过真正的延迟优先级队列完成仲裁、抢占和超时，再调用 `/execute_behavior`。它不维护 `ACT_*` 动作细节，也不直接发布 `/cmd_vel`。

- 节点：`behavior_tree_node`
- 入口：`ros2 launch marsdog_behavior behavior_tree.launch.py`

## 2. 对外接口

### 订阅

| Topic | 类型 | QoS | 作用 |
|---|---|---|---|
| `/perception/audio_event` | String JSON | RELIABLE 10 | 唤醒、强指令、会话结束 |
| `/perception/visual_event` | String JSON | BEST_EFFORT 5 | 视觉 Service 不可用时的场景缓存 |
| `/emotion/state` | String JSON | BEST_EFFORT 5 | 权威情绪当前状态 |
| `/emotion/signal_event` | String JSON | RELIABLE 10 | 情绪上升沿候选 |
| `/internal_need/state` | String JSON | BEST_EFFORT 5 | 权威需求当前状态 |
| `/internal_need/signal_event` | String JSON | RELIABLE 10 | 需求等级变化候选 |

### 调用/发布

| 接口 | 类型 | 作用 |
|---|---|---|
| `/perception/vision/task` | `VisionTask` Client | 人/物上下文路由 |
| `/execute_behavior` | `ExecuteBehavior` Action Client | 发送语义行为 |
| `/behavior/attention_tracking` | String JSON, RELIABLE 10 | 控制会话级视角/跟随模式 |
| `/behavior/result_event` | String JSON, RELIABLE 10 | 把需求行为结果回传 InternalNeed |

## 3. 决策和延迟队列

优先级数值越小越高：Lv0 系统/能源，Lv1 外部指令，Lv2 紧急生理，Lv3 常规生理，Lv4 心理需求，Lv5 情绪，Lv6 idle。

候选排序：

```text
priority_level ASC
sub_priority ASC
emotion_priority ASC
value DESC
created_at DESC
```

当前实现是真正的延迟队列：暂时不能抢占、处于 cooldown 或等待 safe point 的候选保留在池中，直到可执行、权威 state 使其失效或 TTL 到期。不会因当前有更高优先级行为而直接丢弃。

同名 Behavior 使用独立的执行中占位，不进入普通延迟逻辑：一个名字在
`QUEUED` 或 `IN_FLIGHT` 时，其他来源、其他 dedup key 以及
`allow_repeat=true` 的同名事件都会被抑制。成功、失败、超时、取消、抢占、
Goal 拒绝等终态释放占位；未通过相关性检查、实际没有 dispatch 的候选也立即
释放。`allow_repeat` 只表示终态之后可以再次触发，不能产生并发重复动作。

抢占规则：

- 更高优先级候选按当前行为的 `immediate/safe_point/non_interruptible` 策略处理。
- 同级只有强度差至少 15 才尝试抢占。
- 更低优先级不能抢占。
- Lv0 `emergency_stop` 可越过普通中断限制。

`timeout_sec` 是每个行为端到端超时。一般默认 30 秒；充电/到充电点行为在 `config/event_intent_map.yaml` 中为 330 秒，以覆盖 Nav2 默认 300 秒。超时会取消 Action 并产生 `TIMEOUT` 结果。

## 4. 语音会话跟踪

```text
EVT_VOICE_CALL_NAME
  -> /behavior/attention_tracking enabled=true, face_body_centering
  -> 当前 ROS2 运行时不创建 respond_owner_call Action 候选

EVT_VOICE_COMMAND_FOLLOW
  -> enabled=true, follow_owner
  -> 同时发送 follow_owner Action 作为行为确认/handoff

EVT_STATE_CHANGED(state=idle, same interaction_id)
  -> enabled=false
```

跟随生命周期由语音会话决定。`follow_owner` 不能被理解为固定行进动作；实际闭环在动作系统中运行。

从名字唤醒到匹配的 `idle` 结束事件之间，该会话在仲裁中视为虚拟 Lv1
行为：Lv0 安全行为和 Lv1 外部交互仍可执行，Lv2–Lv6 候选保留在候选池中，
待会话结束后恢复调度。这样用户沉默但语音系统仍在等待指令时，不会插入情绪、
需求或空闲动作。

## 5. 视觉上下文

情绪、Hunger、Social、Exploration 可调用 `/perception/vision/task`：

- 情绪：`check_person`，选择 `*WithHuman` 或 `*Alone`。
- Hunger：`detect_objects`，选择进食或寻找食物。
- Social：先查人，无人再查猫/狗。
- Exploration：按识别物品类别选择探索行为。

Service 不可用时回退 Topic 缓存。视觉消息超过约 0.5 秒、目标不是 `tracking` 或 `last_seen_age_ms` 过大时必须按无人/无目标处理，避免视觉节点关闭后仍沿用旧人框。

## 6. 情绪持续表达

`/emotion/signal_event` 只在上升沿创建一次候选。为避免喜悦/兴奋等动作完成后长期静止，当前配置会在权威 state 仍为 triggered 时续排：

```yaml
enabled: true
interval_sec: 0.8
max_cycles: 4
max_duration_sec: 15.0
emotions: [Fear, Anxiety, Excite, Joy, Curious]
```

Calm 不续排。恢复、失败、次数或总时长达到上限时停止。多个情绪同时等待时按 Fear > Anxiety > Excite > Joy > Curious。更高等级行为仍可抢占。

## 7. 需求结果与充电

动作系统的 Action Result 先回到行为树，再由行为树发布 `/behavior/result_event`。只有 `BEHAVIOR_ACTION_MAP` 中的需求行为发布 STARTED/终态；语音、情绪和 idle 不发布。

充电完成必须输出：

```json
{
  "action_type": "ACTION_RECHARGE",
  "demand_type": "Energy",
  "result_type": "COMPLETED",
  "metadata": {"energyValue": 88}
}
```

`energyValue` 是实际电量。缺失时当前兼容策略按 100；长期应改为动作/BMS 提供真实值。充电路线为 Lv0，Lv5 情绪只能排队，不能中断它。

## 8. 配置权威来源

| 文件 | 内容 |
|---|---|
| `config/event_intent_map.yaml` | 事件分类、直接 Behavior、个别超时 |
| `config/intent_action_pool.yaml` | intent 到 Behavior 候选池 |
| `config/emotion_behavior_map.yaml` | 情绪视觉分支和持续表达 |
| `config/behavior_categories.yaml` | 7 层分类与优先级 |
| `docs/event_behavior_table.md` | 当前事件—行为汇总 |

行为树只输出语义 Behavior。新增或改名后必须与动作负责人确认其已精确注册到 `behavior_tree_actions.yaml`。

## 9. 启动与测试

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch marsdog_behavior behavior_tree.launch.py
```

预期日志必须显示真实 `ActionClientAdapter`，否则正在用 Mock。

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest
ros2 topic echo /behavior/attention_tracking
ros2 topic echo /behavior/result_event
ros2 action info /execute_behavior
```

当前系统 ROS 环境中的 `launch_testing` 插件与项目 pytest 版本不兼容，因此上述
命令禁用自动加载的外部插件；项目普通单元测试不依赖它们。当前全量基线为
`278 passed, 18 skipped`，依赖环境差异可造成 skip，但不能新增失败。

## 10. 修改时必须回归

- 不可抢占候选仍留在队列。
- 充电途中 Lv5 情绪不会取消充电。
- 会话结束会关闭 attention tracking。
- 视觉断流不会继续判定有人。
- Action 终态先发布旧行为结果，再启动同 tick 的新行为。
- 需求结果字段和 Energy 方向正确。
- 新事件同步更新白名单、映射配置、动作行为注册和对接归档。
