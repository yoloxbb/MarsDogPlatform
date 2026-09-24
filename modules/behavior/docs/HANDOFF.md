# 行为树项目交接说明

> 对接基线：AudioEvent schema v2 / 行为树显式执行白名单

## 1. 本项目负责什么

行为树是四项目的决策中心：接收语音、视觉、情绪和内部需求，把事件映射为语义 `behavior_name`，通过真正的延迟优先级队列完成仲裁、抢占和超时，再调用 `/execute_behavior`。它不维护 `ACT_*` 动作细节，也不直接发布 `/cmd_vel`。

- 节点：`behavior_tree_node`
- 入口：`ros2 launch marsdog_behavior behavior_tree.launch.py`

## 2. 对外接口

### 订阅

| Topic | 类型 | QoS | 作用 |
|---|---|---|---|
| `/perception/audio_event` | String JSON v2 | RELIABLE 10 | 唤醒、授权具体指令、会话结束 |
| `/perception/visual_event` | String JSON v1 | BEST_EFFORT 5 | STRANGER 融合情绪；FALL/STOP_GESTURE 生成 Lv1.2 候选 |
| `/emotion/state` | String JSON | BEST_EFFORT 5 | 权威情绪当前状态 |
| `/emotion/signal_event` | String JSON | RELIABLE 10 | 情绪上升沿候选 |
| `/internal_need/state` | String JSON | BEST_EFFORT 5 | 权威需求当前状态 |
| `/internal_need/signal_event` | String JSON | RELIABLE 10 | 需求等级变化候选 |

### 调用/发布

| 接口 | 类型 | 作用 |
|---|---|---|
| `/perception/vision/task` | `VisionTask` Client | 人/物上下文路由 |
| `/execute_behavior` | `ExecuteBehavior` Action Client | 发送语义行为 |
| `/behavior/attention_tracking` | String JSON, RELIABLE 10 | 控制语音会话级视角；长期跟随由 `follow_owner` Goal 持有 |
| `/behavior/goal_lease` | String JSON, RELIABLE 10 | 每 0.1 秒按 `goal_id`/`behavior_id` 为运行中的 `follow_owner`、`play_alone` 续租；Action 超过 2 秒未收到续租即停车失败 |
| `/behavior/result_event` | String JSON, RELIABLE 10 | 把需求行为结果回传 InternalNeed |

## 3. 决策和延迟队列

优先级数值越小越高：Lv0 系统/能源，Lv1 外部指令，Lv2 紧急生理，Lv3 常规生理，Lv4 心理需求，Lv5 情绪，Lv6 idle。

候选排序：

```text
priority_level ASC
semantic_rank ASC
modality_rank ASC
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

排队和运行中抢占共用前四项优先级键：事件语义先于传感器来源。
确认人员跌倒的视觉安全事件会排在普通触觉事件之前。抢占规则：

- 更高优先级候选按当前行为的 `immediate/safe_point/non_interruptible` 策略处理。
- 已校验的 `EVT_VOICE_COMMAND_*` 可以接管正在运行的持续性语音行为
  `follow_owner` 或 `play_alone`，不比较 ASR 强度差或行为细分优先级；
  仍须等到安全 Feedback 后请求取消，并在旧 Goal 的真实 Result 到达后下发新 Goal。
- 新一次有效的硬件 `EVT_VOICE_WAKEUP` 也可以接管正在运行的 `follow_owner`
  或 `play_alone`，然后执行 `respond_owner_call` 转向；同样必须等待安全 Feedback
  和旧 Goal 的真实 Result。昵称类社交事件不走这条唤醒链路。
- 优先级键相同通常只有强度差至少 15 才尝试抢占；同一 `interaction_id` 内，显式语音
  指令按 `session_preempt_rank` 优先于唤醒转向/靠近，再服从当前中断策略。
- 除上述持续性语音行为接管外，更低优先级不能抢占。
- Lv0 `emergency_stop` 可越过普通中断限制。

`timeout_sec` 是行为端到端超时；`0` 表示 Tree 不设外层截止时间。
`follow_owner`、`play_alone` 用 `0`，其他行为保留有限超时。充电/到充电点
行为在 `config/event_intent_map.yaml` 中为 330 秒。Action 目前仍把 `0`
解释成立即到期，部署长期行为前必须完成
[Action 长期 Goal 修改](ACTION_LONG_RUNNING_GOALS_REQUIREMENTS.md)。

## 4. 语音会话跟踪

音频入口只接受整数 `schema_version=2`。硬件唤醒和
`EVT_STATE_CHANGED` 是会话生命周期事件；其他语音指令必须存在于
`config/event_intent_map.yaml` 精确白名单，并同时满足
`dispatch_role=specific_command`、`should_trigger_behavior_tree=true`、
`specific_event_type=event_type` 以及预期 `command_id`。不使用 `action`、
`control` 或去掉 `INTENT_` 前缀来推导行为。

具体目录事件不新增笼统的“特殊/常规”标记。同一执行语义复用同一
`behavior_name`，识别来源由 `intent_source` 保留；只有动作目标、目标约束、
安全等级或完成条件不同才新增 Behavior，纯动作风格差异使用 `variant`。Tree 会把
`command_key/command_id/command_catalog_version/intent_source/dispatch_role/`
`specific_event_type` 传入 Action，但会过滤 Voice slots 中仅供参考的
`action_name/behavior`，禁止上游直接选择 Action 单元。完整覆盖状态见
`docs/audio_event_v2_coverage.md`。

19 个 `core: true` 指令现已分别输出独立 Behavior。新增部分为：

```text
WALK          -> walk_to_random_point
GO_OUT        -> go_out_to_play
GO_HOME       -> go_home
APPROACH      -> approach_owner
BACK_UP       -> back_up
STAND_STILL   -> stand_still
HOLD_POSITION -> hold_position
QUIET         -> quiet
```

其中 STAND_UP 只负责切换站姿，STAND_STILL 还会保持站立；HOLD_POSITION 保持
当前姿态；QUIET 只停止声音。后三者均不能提升或替换为 Lv0 emergency_stop。
WALK/GO_OUT/GO_HOME 依赖 Action Nav2，现场需要校准随机 play 区域与 home 点。

```text
EVT_VOICE_WAKEUP
  -> VoiceTask.hold_interaction（有限租约）
  -> respond_owner_call（只按 wake_angle 原地转向）
  -> 等待相同 interaction_id + wake_id 的声纹结果（最多 3 s）
  -> stranger / undetermined / 超时：原地 WAITING，关闭 attention 底盘转向
  -> owner / family：VisionTask.query_targets（2 s 超时，按声源方向选人体）
  -> approach_voice_caller（严格锁定 vision_epoch + target_id）
     -> VisionTask.locate_person_once（一次 SLAM 人体定位）
     -> navigation_required=true 时 Nav2 NavigateToPose（一次目标）
     -> navigation_required=false 时直接完成
  -> 到达：WAITING + face_body_centering；失败：原地 WAITING
  -> release_interaction_hold(reset_idle_timer=true)

EVT_VOICE_COMMAND_FOLLOW
  -> 关闭会话级 attention 控制
  -> 发送独立的长期 follow_owner Goal

EVT_STATE_CHANGED(state=idle, same interaction_id)
  -> 关闭会话级 attention、清理会话范围的排队/待发/运行 Goal
  -> 不取消 follow_owner、play_alone 和已开始的行为范围情绪 Goal
  -> 未开始的语音等待情绪重新解析视觉上下文
```

同一 Voice 会话内新 `wake_id` 会关闭旧唤醒会话并请求取消其 Goal；Tree
仍等待旧 Goal 的真实 Result 才调度新的转向。重复的 `wake_id` 不重发 Goal。
仅匹配当前 `interaction_id + wake_id` 且 `speaker_status=matched` 的
`EVT_VOICE_WAKE_SPEAKER_RESULT` 可决定靠近；`undetermined` 不等同于陌生人，
但两者都不触发靠近。

`EVT_VOICE_CALL_NAME` 与 `EVT_VOICE_COMMAND_CALL_NAME` 是纯社交通知，不得
进入上述唤醒链路，也不得生成通用动作候选。`EVT_VOICE_COMMAND_TOILET/CLEAN/SLEEP`
则在 Tree 内分别检查 `Bladder > 50`、`Cleanliness > 40`、`Sleepiness > 50`，
通过后复用 `barkShortAlert/lickPaws/sleepOnSide`。

`EVT_VOICE_COMMAND_PRAISE/SCOLD` 是非命令的一次性
`audio_reaction`：必须携带 `dispatch_role=social_reaction`、
`is_executable=false`、`should_trigger_behavior_tree=true`。Tree 验证同一
`interaction_id` 后消费当前语音轮次并释放 hold，然后生成 Lv1
候选；若视觉解析到稳定人体目标，会话内只使用
`*InPlaceWithHuman`，不重复靠近。该反应不改写权威 emotion state，
也不启动情绪续排。

Voice 的 `wake_angle` 明确属于 `microphone_array` 原始阵列坐标系；行为树原样
转发 `wake_frame_id`，由 Action 的 wake-orientation 适配器唯一应用安装
offset/sign 并换算为底盘相对旋转，禁止上下游重复标定。

`respond_owner_call`、`approach_voice_caller` 是两个短生命周期 Action；WAITING
不是长期 Goal。`follow_owner` 应由一个持续运行的 Action Goal 持有 UWB 闭环，
不再由语音会话续命；当前 Action 实现仍需按修改需求调整。
转向后只接受相对画面中心 `±25°` 内、未失鲜且带
`vision_epoch + target_id` 的人体；已有明确视觉身份与声纹冲突时拒绝靠近，
未知视觉身份允许按声源方向关联。Vision 不增加声纹身份确认。
查询超时或没有匹配人体会释放 hold。Action 的单次定位失败、Nav2 拒绝、
取消或超时均不得退回 bbox 或直接 `/cmd_vel` 靠近。

当前可执行事件、待 Action 补齐事件及 FETCH 目标参数边界见
[`docs/audio_event_v2_coverage.md`](audio_event_v2_coverage.md)。

语音会话不再一律禁止情绪阈值事件。转向、目标获取、接近、长期跟随 Goal 和
正在执行的高等级行为期间，Tree 保留情绪事件，等可表达时重新核对权威
情绪状态并查询新鲜视觉目标；状态已恢复则撤销等待。`WAITING` 阶段，
或当前语音指令得到真实终态后，如果确认了人物目标，可生成
`*InPlaceWithHuman` 情绪候选，声明 `mobility_policy=in_place`，不再靠近或
重复追踪人物目标；表达动作仍可能包含 Go2/Lite3 底盘动作。Action 的前台执行锁在
Goal 执行期间暂停后台 attention 控制，避免二者同时发布底盘命令。没有人物
目标时等语音 idle 再重新选普通视觉分支。该行为的
`interaction_id` 用于关联与 Action 校验，`lifecycle_scope=behavior` 使已开始
的情绪表达不因语音 idle 被取消。显式指令仍先执行；同会话排队的原地
情绪在新指令到来时撤出，若权威情绪仍有效，则在指令终态后重新解析。
Lv2–Lv6 的其他候选仍受会话注意力门控，Lv0/Lv1 保持原有仲裁规则。

`config/voice_engagement.yaml` 的 `waiting_emotion_enabled` 当前为 `true`，配套
Action 已注册六个 `*InPlaceWithHuman` 并执行 in-place 计划校验。若部署或回退到
旧 Action，必须先将开关设为 `false`，让 Tree 保持 fail-closed，不发送未知
行为名。

## 5. 视觉上下文

情绪、Hunger、Social、Exploration 可调用 `/perception/vision/task`：

- 情绪：`check_person` 选择 `*WithHuman` 或 `*Alone`；启用语音等待原地分支
  后，`WAITING + human` 选择 `*InPlaceWithHuman`。
- Hunger：`detect_objects`，选择进食或寻找食物。
- Social：先查人，无人再查猫/狗。
- Exploration：按识别物品类别选择探索行为。

Service 不可用时回退 Topic 缓存。视觉消息超过约 0.5 秒、目标不是 `tracking` 或 `last_seen_age_ms` 过大时必须按无人/无目标处理，避免视觉节点关闭后仍沿用旧人框。

`events[]` 中 `EVT_VISION_FALL` 和 `EVT_VISION_STOP_GESTURE` 直接进入行为管道，
输出 `respond_person_fall` 和 `respond_stop_gesture`；两者均为
`priority_level=1, sub_priority=12`（Lv1.2）。视觉 Topic 是 10 Hz 状态快照，适配器按事件的
“消失 → 再出现”边沿重新触发，候选池另行保证 queued/in-flight 同名唯一。

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
`358 passed, 18 skipped`，依赖环境差异可造成 skip，但不能新增失败。

## 10. 修改时必须回归

- 不可抢占候选仍留在队列。
- 充电途中 Lv5 情绪不会取消充电。
- 会话结束会关闭 attention tracking、定向丢弃候选并取消匹配 Goal。
- 唤醒转向完成前不冻结视觉目标；无真实距离的正式模式不生成前进 Goal。
- 视觉断流不会继续判定有人。
- Action 终态先发布旧行为结果，再启动同 tick 的新行为。
- 需求结果字段和 Energy 方向正确。
- 新事件同步更新白名单、映射配置、动作行为注册和对接归档。

## play_alone 随机位置自己玩

- Voice 词句：`自己去玩吧`；事件：`EVT_VOICE_COMMAND_PLAY_ALONE`；命令：`CMD_PLAY_ALONE`。
- Tree：`command_play_alone` → `play_alone`，Lv1 / sub_priority=1，立即中断策略，外层无截止时间，冷却 0.2 秒；语音 idle 不取消。
- 沿用 AudioEvent v2 校验：`dispatch_role=specific_command`、匹配的 `specific_event_type`、`should_trigger_behavior_tree=true`；错误命令 ID 或禁止触发时不产生候选。
- 下发独立语义 `behavior_name=play_alone`；Voice 的 `ACT_PLAY_ALONE` 仅为提示，不由 Tree 直接执行。
- Action 当前仅实现一次 `uwb_roam` → `play`，尚未实现同一 Goal 内循环。`ACT_UWB_RANDOM_ROAM` 通过 `/go2/random_roam` 发起 UWB 随机漫游，圆心由服务端冻结在调用时 UWB 位置；默认半径 0.5–2.0 米、请求超时 30 秒。Tree 无需传入点位或坐标。
- 仅漫游返回 `STATUS_SUCCEEDED(4)` 且业务码 `SUCCESS(0)`，并经 Lite3 `finish_navigation()` 确认停稳后，才随机执行一个姿态动作：`ACT_GUARD_DOOR`（扭腰）、`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`（低头）或 `ACT_STRETCH`（降低身体后恢复）。漫游单元预算 40 秒，玩耍单元预算 5 秒。
- 当前实现仅在 Lite3 且 `uwb_follow_enabled=true` 时注册 UWB 漫游适配器，需已启动对应 UWB 服务端。实现说明见 Action 仓库 `docs/PLAY_ALONE_LITE3.md`。
- 完成必须依据真实 Action Result；取消确认 `CANCEL_REQUESTED` 不算完成。若下游失联、终态未知，不能释放控制权或启动下一动作。长期循环及内部有限超时要求见 [Action 修改需求](ACTION_LONG_RUNNING_GOALS_REQUIREMENTS.md)。部署需重建并重启相关节点，再验证实机 UWB 到点、姿态表现和取消停车。
- 验证入口：`tests/test_perception.py` 和 `marsdog_behavior/tests/test_event_to_behavior.py`，覆盖独立映射、事件入队和 AudioEvent v2 拒绝路径。日志应保留完整事件及命令 ID，并能追踪 `play_alone` 候选和执行结果；mock 结果仅证明软件路由。
