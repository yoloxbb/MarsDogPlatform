# Marsdog 内部需求与情绪更新逻辑

完整 ROS2 Topic 输入输出格式见 [ros2_topic_contract.md](ros2_topic_contract.md)。

## 1. 节点入口

当前提供四个 ROS2 节点：

| 节点 | 文件 | 职责 |
|---|---|---|
| `time_controller_node` | `marsdog_ros2/time_controller_node.py` | 权威虚拟时间、动态倍率切换、逐虚拟秒 Tick 发布 |
| `personality_node` | `marsdog_ros2/personality_node.py` | 性格参数维护、性格系数计算、性格状态发布 |
| `internal_need_node` | `marsdog_ros2/internal_need_node.py` | 内部需求计算、需求状态发布、需求等级事件发布 |
| `emotion_engine_node` | `marsdog_ros2/emotion_engine_node.py` | 情绪计算、情绪自然衰减、情绪状态发布、情绪区间事件发布 |


单节点调试命令：

```bash
ros2 run marsdog_behavior personality_node
ros2 run marsdog_behavior time_controller_node
ros2 run marsdog_behavior internal_need_node
ros2 run marsdog_behavior emotion_engine_node
```

四个节点联调建议使用 launch，并选择初始时间模式：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py \
  time_mode:=demo_2h virtual_start_time:=06:00 random_seed:=12345
```

## 2. Topic

### 2.1 输入

| Topic | 类型 | 使用节点 | 说明 |
|---|---|---|---|
| `/perception/audio_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 声音事件输入 |
| `/perception/visual_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 视觉事件输入 |
| `/behavior/result_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 外部结果输入 |
| `/personality/state` | `std_msgs/String` JSON | 需求节点、情绪节点 | 性格参数同步输入 |
| `/simulation/time_state` | `std_msgs/String` JSON | 需求节点、情绪节点 | 权威时间状态和逐虚拟秒 Tick |

### 2.2 输出

| Topic | 类型 | 发布节点 | 发布规则 |
|---|---|---|---|
| `/internal_need/state` | `std_msgs/String` JSON | `internal_need_node` | 每 1 秒持续发布 |
| `/internal_need/signal_event` | `std_msgs/String` JSON | `internal_need_node` | 需求等级变化时发布 |
| `/emotion/state` | `std_msgs/String` JSON | `emotion_engine_node` | 每个虚拟秒发布；真实频率为 1/2/12 Hz |
| `/emotion/signal_event` | `std_msgs/String` JSON | `emotion_engine_node` | 情绪区间或主导情绪变化时发布 |
| `/personality/state` | `std_msgs/String` JSON | `personality_node` | 启动时和性格变化后发布 |
| `/simulation/time_state` | `std_msgs/String` JSON | `time_controller_node` | 初始化、虚拟秒 Tick 和倍率变化时发布 |

## 3. 性格参数同步

性格参数由 `personality_node` 统一维护。用户或调试工具只需要设置 `profile` 或 `A/O/E/C`，不需要设置 `coefficients`。

### 3.1 修改方式

使用 ROS2 参数服务修改：

```bash
ros2 param set /personality_node profile SunnyExplorer
```

或手动设置 `A/O/E/C`：

```bash
ros2 param set /personality_node A 85
ros2 param set /personality_node O 75
ros2 param set /personality_node E 30
ros2 param set /personality_node C 40
```

设置任意 `A/O/E/C` 后，`profile` 会切换为 `Custom`。非法值会被拒绝：

- 未知 `profile`
- `A/O/E/C` 不是整数
- `A/O/E/C` 超出 `0-100`
- 同一次请求里同时设置预设 `profile` 和自定义 `A/O/E/C`

### 3.2 状态输出

`/personality/state` 示例：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "profile": "SunnyExplorer",
  "params": {"A": 90, "O": 80, "E": 95, "C": 70},
  "coefficients": {
    "Joy": 1.82,
    "Excite": 1.87,
    "Anxiety": 1.44,
    "Fear": 0.6,
    "Curious": 2.071,
    "Calm": 1.7,
    "Social": 1.82
  }
}
```

`coefficients` 是只读派生值，由 `A/O/E/C` 自动计算，外部不允许直接设置。

需求节点和情绪节点订阅 `/personality/state` 后更新本地性格参数。性格变化只影响后续计算，不回溯修改已经存在的需求值和情绪值。

## 4. 内部需求状态

所有需求值限制在 `0-100`。

| 变量 | 含义 | 数值语义 |
|---|---|---|
| `Hunger` | 饥渴 | 越高越需要进食/饮水 |
| `Bladder` | 排泄 | 越高越需要排泄 |
| `Sleepiness` | 困倦 | 越高越困 |
| `Cleanliness` | 清洁 | 越高越脏，越需要清洁 |
| `Energy` | 精力/电量 | 越低越需要充电 |
| `Social` | 社交 | 越高越想社交 |
| `Exploration` | 探索 | 越高越想探索 |

`/internal_need/state` 示例：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "demands": {
    "Hunger": {
      "value": 71,
      "triggerThreshold": 70,
      "triggerOperator": "gt",
      "overflowThreshold": 90,
      "triggered": true,
      "overflow": false,
      "level": "TRIGGERED",
      "levelEvent": "NEED_HUNGER_TRIGGERED",
      "levelActive": true
    }
  },
  "levelEvents": {
    "Hunger": "NEED_HUNGER_TRIGGERED",
    "Bladder": "NEED_BLADDER_RECOVERED",
    "Sleepiness": "NEED_SLEEPINESS_RECOVERED",
    "Cleanliness": "NEED_CLEANLINESS_RECOVERED",
    "Energy": "NEED_ENERGY_RECOVERED",
    "Social": "NEED_SOCIAL_RECOVERED",
    "Exploration": "NEED_EXPLORATION_RECOVERED"
  },
  "triggered": [
    {
      "type": "Hunger",
      "value": 71,
      "triggerThreshold": 70,
      "triggerOperator": "gt",
      "overflow": false
    }
  ],
  "sleep": {
    "isSleeping": false,
    "sleepDepth": "Shallow",
    "sleepDurationMinutes": 0,
    "shallowSleepTicksRemaining": 0
  }
}
```

## 5. 内部需求等级事件

每个需求都有 3 个等级：

| 等级 | 含义 |
|---|---|
| `NORMAL` | 未触发 |
| `TRIGGERED` | 超过触发阈值 |
| `OVERFLOW` | 超过满溢阈值 |

需求等级变化时发布 `/internal_need/signal_event`。同一等级不会重复发布。
`/internal_need/state.levelEvents[demand]` 与 `/internal_need/signal_event.event_type`
使用同一套事件名，可直接按 `demand` 对比两者是否一致。

事件命名规则：

```text
NEED_<DEMAND>_TRIGGERED
NEED_<DEMAND>_OVERFLOW
NEED_<DEMAND>_RECOVERED
```

示例：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "event_type": "NEED_HUNGER_TRIGGERED",
  "demand": "Hunger",
  "value": 71,
  "level": "TRIGGERED",
  "previousLevel": "NORMAL",
  "triggerThreshold": 70,
  "triggerOperator": "gt",
  "overflowThreshold": 90,
  "overflowOperator": "gt",
  "trigger": "LEVEL_CHANGED"
}
```

当前自动生成的事件：

| 需求 | 触发事件 | 满溢事件 | 恢复事件 |
|---|---|---|---|
| `Hunger` | `NEED_HUNGER_TRIGGERED` | `NEED_HUNGER_OVERFLOW` | `NEED_HUNGER_RECOVERED` |
| `Bladder` | `NEED_BLADDER_TRIGGERED` | `NEED_BLADDER_OVERFLOW` | `NEED_BLADDER_RECOVERED` |
| `Sleepiness` | `NEED_SLEEPINESS_TRIGGERED` | `NEED_SLEEPINESS_OVERFLOW` | `NEED_SLEEPINESS_RECOVERED` |
| `Cleanliness` | `NEED_CLEANLINESS_TRIGGERED` | `NEED_CLEANLINESS_OVERFLOW` | `NEED_CLEANLINESS_RECOVERED` |
| `Energy` | `NEED_ENERGY_TRIGGERED` | `NEED_ENERGY_OVERFLOW` | `NEED_ENERGY_RECOVERED` |
| `Social` | `NEED_SOCIAL_TRIGGERED` | `NEED_SOCIAL_OVERFLOW` | `NEED_SOCIAL_RECOVERED` |
| `Exploration` | `NEED_EXPLORATION_TRIGGERED` | `NEED_EXPLORATION_OVERFLOW` | `NEED_EXPLORATION_RECOVERED` |

## 6. 内部需求自然更新

`internal_need_node` 从 `/simulation/time_state` 累积虚拟时间，需求公式固定按每
10 个虚拟分钟调用一次：

```python
UpdateNaturalDemandsByTime()
```

三种时间模式对应的真实定时器周期：

| 模式 | 倍率 | 需求 Tick 真实周期 | 完整虚拟 24 小时 |
|---|---:|---:|---:|
| `standard_24h` | 1 | 600 秒 | 24 小时 |
| `demo_12h` | 2 | 300 秒 | 12 小时 |
| `demo_2h` | 12 | 50 秒 | 2 小时 |

虚拟时间按以下公式计算：

```text
virtualDateTime = virtualStartDateTime + monotonicElapsedSeconds * scale
```

时间控制节点和计算节点若因调度延迟错过 Tick，会按虚拟时间顺序逐个补算，
不会合并需求增量。
压缩模式 `virtual_start_time=auto` 从当天虚拟 `06:00` 开始并立即执行晨起初始化。

全局规则：

- `00:00-06:00` 普通需求自然计算锁定。
- `Sleepiness` 是例外，凌晨仍执行困倦规则。
- 离开锁定窗口后执行一次晨起初始化。
- 所有写入统一限制在 `0-100`。

## 7. 各需求规则

### Hunger

- 晨起：`60-70`。
- 白天 `06:00-21:00`：每 Tick `+1`。
- 其他时间：`+0`。
- 触发：`>70`。
- 满溢：`>90`。
- `ACTION_EAT + COMPLETED`：
  - `Hunger -= foodRecovery * portions * eatEfficiency`
  - 进食前 `Hunger > 90`：`Bladder += 25`
  - 进食前 `Hunger > 70`：`Bladder += 20`
  - `Cleanliness += 20`

### Bladder

- 晨起：`20-30`。
- 白天 `06:00-21:00`：每 Tick `+3`。
- 其他时间：`+0`。
- 触发：`>75`。
- 满溢：`>90`。
- `ACTION_DEFECATE + COMPLETED`：`Bladder = 0`。
- `INTERRUPTED / CANCELLED / TIMEOUT`：`Bladder -= 40`。

### Sleepiness

- 晨起：`10-15`。
- 白天 `06:00-21:00`：每 Tick `+4`。
- 夜晚 `21:00-00:00`：每 Tick `+5`。
- 凌晨 `00:00-06:00` 或关灯：清醒状态下 `Sleepiness = 90`。
- 可触发入睡时段：`06:00-00:00`，其中 `06:00-08:00` 强制清醒。
- 触发：`>65`。
- 满溢：`>90`。
- `ACTION_SLEEP + STARTED`：进入浅睡。
- 浅睡持续 14 Tick（140 分钟），每 Tick `Sleepiness -= 2`。
- 浅睡结束后仍 `>65` 时进入深睡。
- 深睡每 Tick `Sleepiness -= 15`。
- 深睡到 `Sleepiness <= 20` 时自然醒来。
- `00:00-06:00` 强制睡眠期间不会自然醒。
- 在睡眠信号被立即响应、无中断且未额外触发关灯的情况下，晨起值 `10-15`
  对应每天约清醒 `6小时40分-6小时50分`、睡眠 `17小时10分-17小时20分`，
  每天约启动 5 次睡眠会话。

### Cleanliness

- 晨起：`5-15`。
- 白天 `06:00-21:00`：每 Tick `+2`。
- 其他时间：`+0`。
- 触发：`>70`。
- 满溢：`>90`。
- 进食完成：`Cleanliness += 20`。
- `ACTION_GROOM + COMPLETED`：`Cleanliness -= 50`。

### Energy

- 当前值等于电量百分比。
- 晨起：`100`。
- 触发：`<20`。
- 满溢：`<10`。
- `ACTION_RECHARGE + COMPLETED`：
  - 有 `metadata.energyValue` 时写入该值。
  - 没有时写入 `100`。

### Social

- 晨起：`random(20,30) * k_social`。
- `k_social = (A/50)*0.8 + (E/50)*0.2`。
- 白天 `06:00-18:00`：每 Tick `+2`。
- 傍晚 `18:00-21:00`：每 Tick `+3`。
- 夜间 `21:00-06:00`：`+0`。
- 触发：`>60`。
- 满溢：`>80`。
- 主人离家状态：单次 `Social += 30`。
- `ACTION_SOCIAL_* + COMPLETED`：
  - `socialOutcome=OwnerInteraction`：`Social -= 25`
  - `socialOutcome=DogHumanResponded`：`Social -= 20`
  - `socialOutcome=DogAnimalResponded`：`Social -= 15`
  - `socialOutcome=Rejected / TimedOut`：不变

### Exploration

- 晨起：`random(10,20) * k_curious`。
- `06:00-21:00` 且 `Energy > 50`：每 Tick `+5`。
- 其他情况：`+0`。
- 触发：`>60`。
- 满溢：`>80`。
- 视觉 `tracked_objects` 不直接改变 `Exploration`，也不保存探索目标上下文。
- `ACTION_EXPLORE* + COMPLETED`：
  - 统一 `Exploration -= 15`
  - `metadata.discoveryType` 会被忽略

## 8. 情绪状态

所有情绪值限制在 `0-100`。

| 变量 | 含义 |
|---|---|
| `Joy` | 愉悦 |
| `Excite` | 兴奋 |
| `Anxiety` | 焦虑 |
| `Fear` | 恐惧 |
| `Curious` | 好奇 |
| `Calm` | 平静 |

`/emotion/state` 持续发布全部情绪值、区间、主导情绪和性格参数。
其中 `levelEvents` 会按情绪名输出当前区间事件名：

```json
{
  "levelEvents": {
    "Joy": "EMO_JOY_LOW",
    "Excite": null,
    "Anxiety": null,
    "Fear": null,
    "Curious": null,
    "Calm": "EMO_CALM_NORMAL"
  }
}
```

`/emotion/state.levelEvents[emotion]` 与 `/emotion/signal_event.event_type`
使用同一套事件名，可直接按 `emotion` 对比两者是否一致。

## 9. 情绪事件计算

外部事件进入 `ApplyEmotionEvent()` 后按配置计算：

```text
finalDelta = round(baseDelta * k_emotion * metadataMultiplier)
```

性格系数：

```text
k_joy     = (A/50)*0.8 + (E/50)*0.2
k_excite  = (A/50)*0.3 + (E/50)*0.7
k_anxiety = (1.5-C/100) * (A/50)
k_fear    = 2.0 - C/50
k_curious = (E/50) * (1 + 0.3*(1-C/100))
k_calm    = (O+A)/100
```

## 10. 情绪自然衰减

`emotion_engine_node` 每个虚拟秒执行一次：

| 情绪 | 衰减 |
|---|---|
| `Joy` | `-2/sec` |
| `Excite` | `-3/sec` |
| `Anxiety` | `-1.5/sec` |
| `Fear` | `-4/sec` |
| `Curious` | `-2/sec` |
| `Calm` | 不自然衰减 |

标准、12 小时和 2 小时模式的真实执行频率分别为 `1 Hz`、`2 Hz` 和 `12 Hz`。
延迟时仍逐虚拟秒补算并检查区间事件，不能把衰减值一次乘倍率后跳过中间区间。

## 11. 时间上下文

四类需求/情绪输出均增加 `timeContext`，原有字段不变。顶层 `timestamp` 表示
真实 Unix 时间，`timeContext.virtualDateTime` 才是需求昼夜计算和压缩测试使用
的时间。完整结构和启动参数见 [ros2_topic_contract.md](ros2_topic_contract.md)。

运行中切换倍率使用：

```bash
ros2 param set /time_controller_node time_mode demo_2h
```

切换时先按旧倍率结算当前虚拟时间，再建立新倍率锚点。`revision` 增加 1，
`virtualDateTime`、需求值、情绪值和睡眠状态均不重置。需求与情绪节点只接受
`/simulation/time_state` 的模式变化，不允许分别修改本地参数。

固定随机种子只影响晨起随机值和情绪随机增量：

```text
random_seed=-1       保持随机
random_seed>=0       可重复
```

## 12. 情绪区间事件

`/emotion/signal_event` 只在情绪区间变化或主导情绪变化时发布。

| 情绪 | 区间 | 事件 |
|---|---|---|
| `Calm` | `0-60` | `EMO_CALM_NORMAL` |
| `Calm` | `61-100` | `EMO_CALM_HIGH` |
| `Joy` | `30-60` | `EMO_JOY_LOW` |
| `Joy` | `61-85` | `EMO_JOY_MID` |
| `Joy` | `86-100` | `EMO_JOY_HIGH` |
| `Excite` | `40-70` | `EMO_EXCITE_LOW` |
| `Excite` | `71-100` | `EMO_EXCITE_HIGH` |
| `Anxiety` | `25-50` | `EMO_ANXIETY_LOW` |
| `Anxiety` | `51-100` | `EMO_ANXIETY_HIGH` |
| `Fear` | `30-60` | `EMO_FEAR_LOW` |
| `Fear` | `61-100` | `EMO_FEAR_HIGH` |
| `Curious` | `20-50` | `EMO_CURIOUS_LOW` |
| `Curious` | `51-100` | `EMO_CURIOUS_HIGH` |

## 13. 行为结果输入

`/behavior/result_event` 是需求值和行为结果情绪变化的输入。消息类型为
`std_msgs/String`，`data` 字段必须是 JSON 对象。

示例：

```json
{
  "event_id": "result-000001",
  "timestamp": 1710000000.0,
  "action_type": "ACTION_EAT",
  "demand_type": "Hunger",
  "result_type": "COMPLETED",
  "metadata": {
    "foodType": "NormalFood",
    "portions": 1,
    "eatEfficiency": "Full"
  }
}
```

字段约束：

| 字段 | 要求 | 说明 |
|---|---|---|
| `event_id` | 建议填写 | 同一节点内重复 `event_id` 只处理一次；不填则无法去重 |
| `timestamp` | 可选 | 当前只透传，不参与计算 |
| `action_type` | 必填 | 必须是已登记的内部需求相关 `ACTION_*` |
| `demand_type` | 建议填写 | 填写时必须与 `action_type` 映射一致，否则拒绝处理 |
| `result_type` | 必填 | 只接受 `STARTED / COMPLETED / FAILED / INTERRUPTED / CANCELLED / TIMEOUT` |
| `metadata` | 必填 JSON 对象 | 没有额外字段时传 `{}`；非对象会被拒绝 |

当前接受的 `action_type -> demand_type`：

| `action_type` | `demand_type` |
|---|---|
| `ACTION_EAT` | `Hunger` |
| `ACTION_DEFECATE` | `Bladder` |
| `ACTION_SLEEP` | `Sleepiness` |
| `ACTION_GROOM` | `Cleanliness` |
| `ACTION_RECHARGE` | `Energy` |
| `ACTION_PLAY_INVITE` | `Social` |
| `ACTION_SOCIAL_GREET` | `Social` |
| `ACTION_BOUNDARY_TEST` | `Social` |
| `ACTION_ATTENTION_SEEK` | `Social` |
| `ACTION_RESOURCE_SHARE` | `Social` |
| `ACTION_EXPLORE` | `Exploration` |
| `ACTION_SPACE_EXPLORE` | `Exploration` |
| `ACTION_OBJECT_EXPLORE` | `Exploration` |

不在上表里的 action 不会更新需求，也不会触发行结果情绪变化。

### 13.1 对需求的影响

| 输入 | 需求处理 |
|---|---|
| `ACTION_EAT + COMPLETED` | 结算 `Hunger / Bladder / Cleanliness` |
| `ACTION_DEFECATE + COMPLETED` | `Bladder = 0` |
| `ACTION_GROOM + COMPLETED` | `Cleanliness -= 50` |
| `ACTION_RECHARGE + COMPLETED` | 写入 `metadata.energyValue`；未提供时写入配置目标值 |
| `ACTION_SLEEP + STARTED` | 进入睡眠状态 |
| `ACTION_SOCIAL_* + COMPLETED` | 按 `metadata.socialOutcome` 结算 `Social` |
| `ACTION_EXPLORE* + COMPLETED` | `Exploration -= 15` |
| `INTERRUPTED / CANCELLED / TIMEOUT` | 对应需求按中断规则扣减 |
| `FAILED` | 需求值不变 |

`metadata` 约束：

| action | metadata |
|---|---|
| `ACTION_EAT` | `foodType=PremiumFood/NormalFood/Snack`，`portions` 为数字，`eatEfficiency=Full/HalfInterrupted` |
| `ACTION_RECHARGE` | `energyValue` 为 `0-100` 数字；也兼容 `energy_value / batteryValue` |
| `ACTION_SOCIAL_*` | `socialOutcome=OwnerInteraction/DogHumanResponded/DogAnimalResponded/Rejected/TimedOut` |
| `ACTION_EXPLORE*` | 当前忽略 metadata |

### 13.2 对情绪的影响

只有通过 action 映射校验的行为结果才会触发行结果情绪变化。`result_type`
映射如下：

| `result_type` | 映射 |
|---|---|
| `COMPLETED` | `DemandSatisfied` |
| `FAILED` | `DemandUnsatisfied` |
| `TIMEOUT` | `DemandUnsatisfied` |
| `INTERRUPTED` | `ActionInterrupted` |
| `CANCELLED` | `ActionInterrupted` |

当前情绪变化：

| 映射 | 情绪变化 |
|---|---|
| `DemandSatisfied` | `Joy +10~20`，`Calm +5~10`，`Anxiety -15~-5` |
| `DemandUnsatisfied` | `Anxiety +5~15` |
| `ActionInterrupted` | `Anxiety +3~5` |

## 14. 测试命令

```bash
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

三档时间压缩的测试移交流程见
[time_compression_test_guide.md](time_compression_test_guide.md)。
