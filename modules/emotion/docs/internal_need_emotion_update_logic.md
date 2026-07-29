# Marsdog 内部需求与情绪更新逻辑

完整 ROS2 Topic 输入输出格式见 [ros2_topic_contract.md](ros2_topic_contract.md)。

## 1. 节点入口

当前提供四个 ROS2 节点：

| 节点 | 文件 | 职责 |
|---|---|---|
| `time_controller_node` | `marsdog_ros2/time_controller_node.py` | 权威虚拟时间、动态倍率切换、逐虚拟秒 Tick 发布 |
| `personality_node` | `marsdog_ros2/personality_node.py` | 性格参数维护、性格系数计算、性格状态发布 |
| `internal_need_node` | `marsdog_ros2/internal_need_node.py` | 内部需求计算、需求状态发布、需求等级事件发布 |
| `emotion_engine_node` | `marsdog_ros2/emotion_engine_node.py` | 情绪计算、情绪自然衰减、情绪状态发布、情绪阈值事件发布 |


单节点调试命令：

```bash
ros2 run marsdog_need_emotion personality_node
ros2 run marsdog_need_emotion time_controller_node
ros2 run marsdog_need_emotion internal_need_node
ros2 run marsdog_need_emotion emotion_engine_node
```

四个节点联调建议使用 launch，并选择初始时间模式：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=24 virtual_start_time:=06:00 random_seed:=12345
```

只测试凌晨睡眠和晨起重置时，可在30秒内运行虚拟 `00:00-06:00`：

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 random_seed:=12345
```

该测试使用36个虚拟10分钟离散步骤，并自动回传一次
`ACTION_SLEEP + STARTED`。生产 `time_scale` 的 `1-100` 限制不变。

与外部行为模块连续联调时，使用统一时间节点的每日凌晨加速：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

该模式不会自动回传睡眠行为，也不会在06:00退出。行为模块收到
`NEED_SLEEPINESS_TRIGGERED` 后需要及时发布 `ACTION_SLEEP + STARTED`；
06:00需求系统自动醒来，时间节点继续按所选基础倍率推进，并在下一天00:00
再次加速。`time_scale=1-100` 均可启用该模式，加速期间也可以动态切换基础倍率。

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
| `/emotion/state` | `std_msgs/String` JSON | `emotion_engine_node` | 每个虚拟秒发布；真实频率为 `time_scale` Hz |
| `/emotion/signal_event` | `std_msgs/String` JSON | `emotion_engine_node` | 情绪首次达到触发阈值时发布 |
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
| `Energy` | 充电需求/电量缺口 | `100 - 当前电量百分比`，越高越需要充电 |
| `Social` | 社交 | 越高越想社交 |
| `Exploration` | 探索 | 越高越想探索 |

`/internal_need/state` 示例：

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "demands": {
    "Hunger": {
      "value": 71,
      "triggerThreshold": 70,
      "triggerOperator": "gt",
      "urgentThreshold": null,
      "urgentOperator": null,
      "overflowThreshold": 90,
      "triggered": true,
      "urgent": false,
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
      "urgentThreshold": null,
      "urgentOperator": null,
      "urgent": false,
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

需求按最多 4 个等级计算，没有配置对应阈值的等级会跳过：

| 等级 | 含义 |
|---|---|
| `NORMAL` | 未触发 |
| `TRIGGERED` | 超过触发阈值 |
| `URGENT` | 超过可选的中间紧急阈值 |
| `OVERFLOW` | 超过满溢阈值 |

当前阈值：

| 需求 | NORMAL | TRIGGERED | URGENT | OVERFLOW |
|---|---|---|---|---|
| `Hunger` | `0-70` | `71-90` | 无 | `91-100` |
| `Bladder` | `0-75` | `76-100` | 无 | 无 |
| `Sleepiness` | `0-65` | `66-90` | 无 | `91-100` |
| `Cleanliness` | `0-70` | `71-100` | 无 | 无 |
| `Energy` | `0-80` | `81-90` | 无 | `91-100` |
| `Social` | `0-60` | `61-70` | `71-85` | `86-100` |
| `Exploration` | `0-60` | `61-100` | 无 | 无 |

需求等级变化时发布 `/internal_need/signal_event`。同一等级不会重复发布。
`/internal_need/state.levelEvents[demand]` 与 `/internal_need/signal_event.event_type`
使用同一套事件名，可直接按 `demand` 对比两者是否一致。

事件命名规则：

```text
NEED_<DEMAND>_TRIGGERED
NEED_<DEMAND>_URGENT
NEED_<DEMAND>_OVERFLOW
NEED_<DEMAND>_RECOVERED
```

示例：

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "event_type": "NEED_HUNGER_TRIGGERED",
  "demand": "Hunger",
  "value": 71,
  "level": "TRIGGERED",
  "previousLevel": "NORMAL",
  "triggerThreshold": 70,
  "triggerOperator": "gt",
  "urgentThreshold": null,
  "urgentOperator": null,
  "overflowThreshold": 90,
  "overflowOperator": "gt",
  "trigger": "LEVEL_CHANGED"
}
```

当前自动生成的事件：

| 需求 | 触发事件 | 中间紧急事件 | 满溢事件 | 恢复事件 |
|---|---|---|---|---|
| `Hunger` | `NEED_HUNGER_TRIGGERED` | 无 | `NEED_HUNGER_OVERFLOW` | `NEED_HUNGER_RECOVERED` |
| `Bladder` | `NEED_BLADDER_TRIGGERED` | 无 | 无 | `NEED_BLADDER_RECOVERED` |
| `Sleepiness` | `NEED_SLEEPINESS_TRIGGERED` | 无 | `NEED_SLEEPINESS_OVERFLOW` | `NEED_SLEEPINESS_RECOVERED` |
| `Cleanliness` | `NEED_CLEANLINESS_TRIGGERED` | 无 | 无 | `NEED_CLEANLINESS_RECOVERED` |
| `Energy` | `NEED_ENERGY_TRIGGERED` | 无 | `NEED_ENERGY_OVERFLOW` | `NEED_ENERGY_RECOVERED` |
| `Social` | `NEED_SOCIAL_TRIGGERED` | `NEED_SOCIAL_URGENT` | `NEED_SOCIAL_OVERFLOW` | `NEED_SOCIAL_RECOVERED` |
| `Exploration` | `NEED_EXPLORATION_TRIGGERED` | 无 | 无 | `NEED_EXPLORATION_RECOVERED` |

## 6. 内部需求自然更新

`internal_need_node` 从 `/simulation/time_state` 累积虚拟时间，需求公式固定按每
10 个虚拟分钟调用一次：

```python
UpdateNaturalDemandsByTime()
```

未启用凌晨特殊加速时，`time_scale` 允许 `1-100` 的整数。需求 Tick 真实周期为
`600 / time_scale` 秒，完整虚拟 24 小时的真实耗时为
`24 / time_scale` 小时。情绪状态仍跟随虚拟秒发布，但情绪自然衰减独立按
真实时间 1 Hz 执行。

虚拟时间按以下公式计算：

```text
virtualDateTime = virtualStartDateTime + monotonicElapsedSeconds * scale
```

时间控制节点和计算节点若因调度延迟错过 Tick，会按虚拟时间顺序逐个补算，
不会合并需求增量。
`virtual_start_time=auto` 时，1 倍从当前真实时间开始，2-100 倍从当天虚拟
`06:00` 开始并立即执行晨起初始化。

全局规则：

- `00:00-06:00` 普通需求自然计算锁定。
- `Sleepiness` 是例外，凌晨仍执行困倦规则。
- `Energy` 也是例外，睡眠和凌晨锁定期间仍持续耗电。
- 离开锁定窗口后执行一次晨起初始化，但不重置 Energy。
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
- 不配置满溢等级，到 `100` 仍为 `TRIGGERED`。
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
- 不配置满溢等级，到 `100` 仍为 `TRIGGERED`。
- 进食完成：`Cleanliness += 20`。
- `ACTION_GROOM + COMPLETED`：`Cleanliness -= 50`。

### Energy

- `Energy = 100 - 当前电量百分比`。
- 每次节点启动为满电：`Energy = 0`。
- 每天 06:00 的晨起初始化不重置 Energy，不会凭空恢复电量。
- 满电续航为 2 个虚拟小时；每 10 个虚拟分钟结算一次，12 个 Tick 后
  `Energy = 100`。
- 每 Tick 的理论增量是 `100 / 12`，实现通过累计小数余量得到
  `8, 16, 25, 33, 41, 50, 58, 66, 75, 83, 91, 100` 的轨迹。
- 普通时段耗电跟随权威虚拟时间，遗漏 Tick 会补算；24 倍时 5 分钟真实时间
  耗尽，100 倍时 72 秒耗尽。
- 凌晨特殊加速是例外：虚拟 6 小时压缩到 30 秒时，Energy 只按 1 倍累计
  30 秒耗电，不按 6 个虚拟小时耗电。
- 30 秒相当于满电的约 `0.4167%`，当前整数 Energy 仍显示0；小数余量保留，
  后续继续累计，累计到72秒时电量下降1%。
- 触发：`>80`，等价于电量 `<20%`。
- 满溢：`>90`，等价于电量 `<10%`。
- `ACTION_RECHARGE + COMPLETED`：
  - `metadata.energyValue` 表示电量百分比，保存时写入 `100 - energyValue`。
  - 没有 metadata 时使用目标电量 `100%`，写入 `Energy = 0`。

### Social

- 晨起：`random(20,30) * k_social`。
- `k_social = (A/50)*0.8 + (E/50)*0.2`。
- 白天 `06:00-18:00`：每 Tick `+2`。
- 傍晚 `18:00-21:00`：每 Tick `+3`。
- 夜间 `21:00-06:00`：`+0`。
- 触发：`>60`。
- 中间紧急：`>70`。
- 满溢：`>85`。
- 主人离家状态：单次 `Social += 30`。
- `ACTION_SOCIAL_* + COMPLETED`：
  - `socialOutcome=OwnerInteraction`：`Social -= 25`
  - `socialOutcome=DogHumanResponded`：`Social -= 20`
  - `socialOutcome=DogAnimalResponded`：`Social -= 15`
  - `socialOutcome=Rejected / TimedOut`：不变

### Exploration

- 晨起：`random(10,20) * k_curious`。
- `06:00-21:00` 且 `Energy < 50`（电量 `>50%`）：每 Tick `+5`。
- 其他情况：`+0`。
- 触发：`>60`。
- 不配置满溢等级，到 `100` 仍为 `TRIGGERED`。
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

`/emotion/state` 使用 `schema_version=2.0`，持续发布全部情绪值、单一阈值、
触发状态、主导情绪和性格参数：

```json
{
  "emotions": {
    "Joy": {
      "value": 35,
      "triggerThreshold": 30,
      "triggerOperator": "gte",
      "triggered": true
    }
  },
  "dominantEmotion": "Joy"
}
```

情绪状态不再包含 `levelEvents / dominantEmotionSignal / level / range` 等层级
字段。`dominantEmotion` 仍按最大情绪值计算，但不参与信号事件生成。

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

`emotion_engine_node` 使用单调真实时钟每个真实秒执行一次：

| 情绪 | 衰减 |
|---|---|
| `Joy` | `-2/sec` |
| `Excite` | `-3/sec` |
| `Fear` | `-4/sec` |
| `Curious` | `-2/sec` |
| `Anxiety` | 不自然衰减 |
| `Calm` | 不自然衰减 |

真实执行频率固定为 1 Hz，不受 `time_scale` 和运行时倍率切换影响。
节点延迟时仍逐真实秒补算并检查阈值状态，不能把多秒衰减值一次合并。该定时器
只衰减配置了正数速率的情绪，`Anxiety` 仍可由感知事件和
行为结果增减。虚拟 Tick 只负责情绪状态的时间上下文和发布节奏。

## 11. 时间上下文

四类需求/情绪输出均增加 `timeContext`，原有字段不变。顶层 `timestamp` 表示
真实 Unix 时间，`timeContext.virtualDateTime` 才是需求昼夜计算和压缩测试使用
的时间。完整结构和启动参数见 [ros2_topic_contract.md](ros2_topic_contract.md)。

运行中切换倍率使用：

```bash
ros2 param set /time_controller_node time_scale 100
```

切换时先按旧倍率结算当前虚拟时间，再建立新倍率锚点。`revision` 增加 1，
`virtualDateTime`、需求值、情绪值和睡眠状态均不重置。需求与情绪节点只接受
`/simulation/time_state` 的倍率变化，不允许分别修改本地参数。

`timeContext.scale` 是基础连续倍率。兼容字段 `mode` 在倍率 `1/2/12`
时分别为 `standard_24h / demo_12h / demo_2h`，其他倍率为 `custom`，不参与计算。
凌晨加速期间以权威 `virtualDateTime` 跳步，并通过 `effectiveScale` 表示实际速度。

固定随机种子只影响晨起随机值和情绪随机增量：

```text
random_seed=-1       保持随机
random_seed>=0       可重复
```

## 12. 情绪阈值事件

`/emotion/signal_event` 使用 `schema_version=2.0`，只在情绪从未触发变为已
触发时发布。触发后继续升高、主导情绪变化和降到阈值以下都不发布事件；降到
阈值以下会更新内部快照，因此以后再次达到阈值时能够重新触发。

| 情绪 | 触发条件 | 事件 |
|---|---|---|
| `Calm` | `>=0` | `EMO_CALM_TRIGGERED`；启动快照为已触发，不主动发送 |
| `Joy` | `>=30` | `EMO_JOY_TRIGGERED` |
| `Excite` | `>=40` | `EMO_EXCITE_TRIGGERED` |
| `Anxiety` | `>=25` | `EMO_ANXIETY_TRIGGERED` |
| `Fear` | `>=30` | `EMO_FEAR_TRIGGERED` |
| `Curious` | `>=20` | `EMO_CURIOUS_TRIGGERED` |

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
| `ACTION_RECHARGE + COMPLETED` | 将 metadata 中的电量百分比转换为 Energy；未提供时使用配置目标电量 |
| `ACTION_SLEEP + STARTED` | 进入睡眠状态 |
| `ACTION_SOCIAL_* + COMPLETED` | 按 `metadata.socialOutcome` 结算 `Social` |
| `ACTION_EXPLORE* + COMPLETED` | `Exploration -= 15` |
| `INTERRUPTED / CANCELLED / TIMEOUT` | 对应需求按中断规则扣减 |
| `FAILED` | 需求值不变 |

`metadata` 约束：

| action | metadata |
|---|---|
| `ACTION_EAT` | `foodType=PremiumFood/NormalFood/Snack`，`portions` 为数字，`eatEfficiency=Full/HalfInterrupted` |
| `ACTION_RECHARGE` | `energyValue` 为充电后的 `0-100` 电量百分比；也兼容 `energy_value / batteryValue` |
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

整数倍率时间压缩的测试移交流程见
[time_compression_test_guide.md](time_compression_test_guide.md)。
