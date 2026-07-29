# Marsdog 当前实现总结

完整 ROS2 Topic 输入输出格式见 [ros2_topic_contract.md](ros2_topic_contract.md)。

本文档记录当前仓库的实现状态。当前版本包含：

- 内部需求计算
- 情绪计算
- 性格参数与性格系数计算
- ROS2 输入适配
- ROS2 状态/事件发布
- 行为结果数值结算

## 1. 代码结构

| 路径 | 说明 |
|---|---|
| `marsdog_core/need_system.py` | 内部需求计算统一入口 `MarsdogNeedSystem` |
| `marsdog_core/emotion_system.py` | 情绪计算统一入口 `MarsdogEmotionSystem` |
| `marsdog_core/personality_system.py` | 性格参数统一入口 `MarsdogPersonalitySystem` |
| `marsdog_core/time_controller.py` | `1-100` 整数倍率虚拟时钟和遗漏 Tick 补算调度器 |
| `marsdog_core/*_behavior.py` | 各需求的数值增长、恢复和结果结算逻辑 |
| `marsdog_ros2/time_controller_node.py` | 权威虚拟时间与运行时倍率控制节点 |
| `marsdog_ros2/midnight_test_node.py` | 30秒离散推进虚拟凌晨并自动完成睡眠握手的测试时间源 |
| `marsdog_ros2/time_state_adapter.py` | 适配 `/simulation/time_state` |
| `marsdog_ros2/internal_need_node.py` | 发布 `/internal_need/state` 和 `/internal_need/signal_event` |
| `marsdog_ros2/emotion_engine_node.py` | 发布 `/emotion/state` 和 `/emotion/signal_event` |
| `marsdog_ros2/personality_node.py` | 维护性格参数并发布 `/personality/state` |
| `marsdog_ros2/perception_adapter.py` | 适配 `/perception/audio_event`、`/perception/visual_event` |
| `marsdog_ros2/behavior_result_adapter.py` | 适配 `/behavior/result_event` |
| `marsdog_ros2/personality_adapter.py` | 适配 `/personality/state` |
| `marsdog_ros2/time_context.py` | 为需求/情绪输出附加统一虚拟时间上下文 |
| `configs/demands.yaml` | 内部需求阈值、增长、恢复配置 |
| `configs/emotions.yaml` | 情绪阈值、区间事件、衰减、事件映射配置 |
| `configs/personality.yaml` | 性格预设 |

## 2. ROS2 接口

### 输入

| Topic | 类型 | 节点 | 说明 |
|---|---|---|---|
| `/perception/audio_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 声音事件，直接读取 `event_type` |
| `/perception/visual_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 视觉事件，读取 `events[]` 和目标字段 |
| `/behavior/result_event` | `std_msgs/String` JSON | 需求节点、情绪节点 | 外部结果输入 |
| `/personality/state` | `std_msgs/String` JSON | 需求节点、情绪节点 | 性格参数同步输入 |
| `/simulation/time_state` | `std_msgs/String` JSON | 需求节点、情绪节点 | 权威时间状态和逐虚拟秒 Tick |

本层不调用感知服务，不主动请求找人、找物或动物识别。

### 输出

| Topic | 类型 | 节点 | 说明 |
|---|---|---|---|
| `/internal_need/state` | `std_msgs/String` JSON | `internal_need_node` | 全量内部需求状态，1 秒持续发布 |
| `/internal_need/signal_event` | `std_msgs/String` JSON | `internal_need_node` | 需求等级变化时发布 |
| `/emotion/state` | `std_msgs/String` JSON | `emotion_engine_node` | 全量情绪状态，每个虚拟秒发布 |
| `/emotion/signal_event` | `std_msgs/String` JSON | `emotion_engine_node` | 情绪区间或主导情绪变化时发布 |
| `/personality/state` | `std_msgs/String` JSON | `personality_node` | 性格状态，启动时和性格变化后发布 |
| `/simulation/time_state` | `std_msgs/String` JSON | `time_controller_node` | 时间初始化、逐秒 Tick、倍率变化 |
| `/simulation/midnight_test_result` | `std_msgs/String` JSON | `midnight_test_node` | 凌晨场景完成状态和最终需求/睡眠快照 |

## 3. 内部需求输出

`/internal_need/state` 示例结构：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "demands": {
    "Hunger": {
      "value": 65,
      "triggerThreshold": 70,
      "triggerOperator": "gt",
      "overflowThreshold": 90,
      "triggered": false,
      "overflow": false,
      "level": "NORMAL",
      "levelEvent": "NEED_HUNGER_RECOVERED",
      "levelActive": false
    }
  },
  "levelEvents": {
    "Hunger": "NEED_HUNGER_RECOVERED",
    "Bladder": "NEED_BLADDER_RECOVERED",
    "Sleepiness": "NEED_SLEEPINESS_RECOVERED",
    "Cleanliness": "NEED_CLEANLINESS_RECOVERED",
    "Energy": "NEED_ENERGY_RECOVERED",
    "Social": "NEED_SOCIAL_RECOVERED",
    "Exploration": "NEED_EXPLORATION_RECOVERED"
  },
  "triggered": [],
  "sleep": {
    "isSleeping": false,
    "sleepDepth": "Shallow",
    "sleepDurationMinutes": 0,
    "shallowSleepTicksRemaining": 0
  }
}
```

`/internal_need/signal_event` 只在需求等级变化时发布一次。
`/internal_need/state.levelEvents[demand]` 与 signal 事件里的 `event_type`
使用同一套事件名，可直接对比。

## 4. 情绪输出

`/emotion/state` 示例结构：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "emotions": {
    "Joy": {
      "value": 35,
      "triggerThreshold": 30,
      "triggerOperator": "gte",
      "triggered": true,
      "level": "LOW",
      "levelEvent": "EMO_JOY_LOW",
      "levelRange": [30, 60],
      "levelActive": true
    }
  },
  "levelEvents": {
    "Joy": "EMO_JOY_LOW",
    "Excite": null,
    "Anxiety": null,
    "Fear": null,
    "Curious": null,
    "Calm": "EMO_CALM_NORMAL"
  },
  "triggered": [],
  "dominantEmotion": "Joy",
  "dominantEmotionSignal": {
    "emotion": "Joy",
    "value": 35,
    "level": "LOW",
    "eventType": "EMO_JOY_LOW",
    "range": [30, 60],
    "active": true
  },
  "personality": {"A": 50, "O": 50, "E": 50, "C": 50},
  "lastEmotionEventResult": {}
}
```

`/emotion/signal_event` 只在区间变化或主导情绪变化时发布，例如：
`/emotion/state.levelEvents[emotion]` 与 signal 事件里的 `event_type`
使用同一套事件名，可直接对比。

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "event_type": "EMO_JOY_LOW",
  "emotion": "Joy",
  "value": 35,
  "level": "LOW",
  "range": [30, 60],
  "trigger": "LEVEL_CHANGED_AND_DOMINANT_CHANGED",
  "isDominant": true,
  "dominantChanged": true
}
```

## 5. 性格输出

性格参数由 `personality_node` 统一维护。用户设置 `profile` 或 `A/O/E/C`，系统自动计算 `coefficients`。

设置预设：

```bash
ros2 param set /personality_node profile SunnyExplorer
```

设置自定义参数：

```bash
ros2 param set /personality_node A 85
ros2 param set /personality_node O 75
ros2 param set /personality_node E 30
ros2 param set /personality_node C 40
```

`/personality/state` 示例结构：

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

`coefficients` 是只读派生值，外部不直接设置。需求节点和情绪节点订阅 `/personality/state` 后，同步后续计算使用的 `A/O/E/C`。

## 6. 需求逻辑

### 全局规则

- 每 10 分钟更新一次自然需求。
- `00:00-06:00` 普通需求自然计算锁定。
- `Sleepiness` 是例外：凌晨清醒时强制设为 `90`，睡眠中继续恢复。
- 离开锁定期后执行晨起初始化。
- 内部需求行为被 `INTERRUPTED / CANCELLED / TIMEOUT` 时，按 `actionDemandMap` 找到需求并扣减。
- 默认中断扣减 `-20`，`Bladder` 专属中断扣减 `-40`。

### Hunger

- 晨起：`60-70`。
- 白天 `06:00-21:00`：每 Tick `+1`。
- 其他时间：`+0`。
- 触发：`>70`。
- 满溢：`>90`。
- 行为结果 `ACTION_EAT + COMPLETED`：
  - `Hunger -= foodRecovery * portions * eatEfficiency`
  - `Bladder += 25`，当进食前 `Hunger > 90`
  - `Bladder += 20`，当进食前 `Hunger > 70`
  - `Cleanliness += 20`

### Bladder

- 晨起：`20-30`。
- 白天 `06:00-21:00`：每 Tick `+3`。
- 其他时间：`+0`。
- 触发：`>75`。
- 满溢：`>90`。
- 行为结果 `ACTION_DEFECATE + COMPLETED`：`Bladder = 0`。

### Sleepiness

- 晨起：`10-15`。
- 白天 `06:00-21:00`：每 Tick `+4`。
- 夜晚 `21:00-00:00`：每 Tick `+5`。
- 凌晨 `00:00-06:00` 或关灯：清醒状态下 `Sleepiness = 90`。
- 可触发入睡时段：`06:00-00:00`，其中 `06:00-08:00` 强制清醒。
- 触发：`>65`。
- 满溢：`>90`。
- `ACTION_SLEEP + STARTED`：进入浅睡。
- 浅睡固定 14 Tick（140 分钟），每 Tick `-2`。
- 浅睡结束后仍 `>65` 则进入深睡，否则醒来。
- 深睡每 Tick `-15`，直到 `<=20` 自然醒来。
- `00:00-06:00` 强制睡眠期间不会自然醒。
- 睡眠信号被立即响应且无中断时，每天约清醒 `6小时40分-6小时50分`，
  睡眠 `17小时10分-17小时20分`，约启动 5 次睡眠会话。

### Cleanliness

- 晨起：`5-15`。
- 白天 `06:00-21:00`：每 Tick `+2`。
- 其他时间：`+0`。
- 触发：`>70`。
- 满溢：`>90`。
- 进食完成：`+20`。
- `ACTION_GROOM + COMPLETED`：`Cleanliness -= 50`。

### Energy

- 表示充电需求/电量缺口：`Energy = 100 - 当前电量百分比`。
- 每次节点启动为满电：`Energy = 0`；每天 06:00 晨起重置不会自动充电。
- 满电续航为 2 个虚拟小时，每个虚拟 10 分钟 Tick 线性增加 Energy，并用
  小数余量保证第 12 个 Tick 恰好到 `Energy = 100`。
- Energy 不受凌晨普通需求锁定和睡眠影响；普通时段和遗漏 Tick 按权威虚拟
  时间补算。
- 启用凌晨特殊加速时，`00:00-06:00` 不按 6 个虚拟小时耗电，而是按该窗口
  的真实持续时间以 1 倍耗电；默认30秒窗口只累计30秒耗电。
- 30秒仅消耗满电的约 `0.4167%`，对外整数电量仍为100%，小数余量会保留到
  后续 Tick 继续累计。
- `time_scale=S` 时，两虚拟小时对应 `7200/S` 秒真实时间；24 倍为 5 分钟，
  100 倍为 72 秒；这个换算只用于非凌晨特殊加速时段。
- 触发：`>80`，等价于电量 `<20%`。
- 满溢：`>90`，等价于电量 `<10%`。
- `ACTION_RECHARGE + COMPLETED`：
  - `metadata.energyValue` 表示充电后的电量百分比，保存时转换成 Energy。
  - 没有 metadata 时充电到配置目标 `100%`，即 `Energy = 0`。

### Social

- 数值越高表示社交欲望越强。
- 晨起：`random(20,30) * k_social`。
- `k_social = k_joy = (A/50)*0.8 + (E/50)*0.2`。
- 白天 `06:00-18:00`：每 Tick `+2`。
- 傍晚 `18:00-21:00`：每 Tick `+3`。
- 夜间 `21:00-06:00`：`+0`。
- 触发：`>60`。
- 满溢：`>80`。
- 明确 `OwnerLeftHome`：单次 `+30`。
- `ACTION_SOCIAL_* + COMPLETED` 根据 `metadata.socialOutcome` 结算：
  - `OwnerInteraction`：`-25`
  - `DogHumanResponded`：`-20`
  - `DogAnimalResponded`：`-15`
  - `Rejected / TimedOut`：不变

### Exploration

- 数值越高表示探索欲望越强。
- 晨起：`random(10,20) * k_curious`。
- 白天 `06:00-21:00` 且 `Energy < 50`（电量 `>50%`）：每 Tick `+5`。
- 其他时间或精力不足：`+0`。
- 触发：`>60`。
- 满溢：`>80`。
- 视觉 `tracked_objects` 不直接改变 `Exploration`，也不保存探索目标上下文。
- `ACTION_EXPLORE* + COMPLETED` 统一 `Exploration -= 15`，忽略 `metadata.discoveryType`。

## 7. 情绪逻辑

### 情绪类型

- `Joy`
- `Excite`
- `Anxiety`
- `Fear`
- `Curious`
- `Calm`

所有情绪值统一限制在 `0-100`。

### 性格系数

```text
k_joy     = (A/50)*0.8 + (E/50)*0.2
k_excite  = (A/50)*0.3 + (E/50)*0.7
k_anxiety = (1.5-C/100) * (A/50)
k_fear    = 2.0 - C/50
k_curious = (E/50) * (1 + 0.3*(1-C/100))
k_calm    = (O+A)/100
```

外部事件情绪增量：

```text
finalDelta = round(baseDelta * k_emotion * metadataMultiplier)
```

### 自然衰减

情绪节点按单调真实时间每 1 秒执行一次，不随 `time_scale` 加速：

- `Joy -= 2/sec`
- `Excite -= 3/sec`
- `Fear -= 4/sec`
- `Curious -= 2/sec`
- `Anxiety` 不自然衰减
- `Calm` 不自然衰减

### 情绪区间事件

当前配置：

| 情绪 | 区间 | 事件 |
|---|---|---|
| Calm | `0-60` | `EMO_CALM_NORMAL` |
| Calm | `61-100` | `EMO_CALM_HIGH` |
| Joy | `30-60` | `EMO_JOY_LOW` |
| Joy | `61-85` | `EMO_JOY_MID` |
| Joy | `86-100` | `EMO_JOY_HIGH` |
| Excite | `40-70` | `EMO_EXCITE_LOW` |
| Excite | `71-100` | `EMO_EXCITE_HIGH` |
| Anxiety | `25-50` | `EMO_ANXIETY_LOW` |
| Anxiety | `51-100` | `EMO_ANXIETY_HIGH` |
| Fear | `30-60` | `EMO_FEAR_LOW` |
| Fear | `61-100` | `EMO_FEAR_HIGH` |
| Curious | `20-50` | `EMO_CURIOUS_LOW` |
| Curious | `51-100` | `EMO_CURIOUS_HIGH` |

## 8. 行为结果输入

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
| `event_id` | 建议填写 | 重复 `event_id` 只处理一次；不填则无法去重 |
| `timestamp` | 可选 | 当前只透传，不参与计算 |
| `action_type` | 必填 | 必须是内部需求相关 `ACTION_*` |
| `demand_type` | 建议填写 | 填写时必须与 `action_type` 映射一致 |
| `result_type` | 必填 | `STARTED / COMPLETED / FAILED / INTERRUPTED / CANCELLED / TIMEOUT` |
| `metadata` | 必填 JSON 对象 | 没有额外字段时传 `{}` |

当前接受的 action：

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

不在上表里的 action 会被忽略，不更新需求，也不触发行结果情绪变化。

需求节点处理：

- `COMPLETED`：按 action 类型结算对应需求。
- `STARTED + ACTION_SLEEP`：进入睡眠状态。
- `INTERRUPTED / CANCELLED / TIMEOUT`：按对应需求扣减。
- `FAILED`：需求值不变。

情绪节点处理：

- `COMPLETED` -> `DemandSatisfied`
- `FAILED / TIMEOUT` -> `DemandUnsatisfied`
- `INTERRUPTED / CANCELLED` -> `ActionInterrupted`

关键 metadata：

| action | metadata |
|---|---|
| `ACTION_EAT` | `foodType=PremiumFood/NormalFood/Snack`，`portions` 为数字，`eatEfficiency=Full/HalfInterrupted` |
| `ACTION_RECHARGE` | `energyValue` 为充电后的 `0-100` 电量百分比；兼容 `energy_value / batteryValue` |
| `ACTION_SOCIAL_*` | `socialOutcome=OwnerInteraction/DogHumanResponded/DogAnimalResponded/Rejected/TimedOut` |
| `ACTION_EXPLORE*` | 当前忽略 metadata |

## 9. 运行方式

Python 单元测试：

```bash
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

ROS2 节点：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=1
```

时间压缩倍率：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py time_scale:=7
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 virtual_start_time:=06:00 random_seed:=12345
```

未启用凌晨特殊加速时，`time_scale` 允许 `1-100` 的整数。需求 Tick 真实周期为
`600 / time_scale` 秒，情绪状态真实发布频率为 `time_scale` Hz，完整虚拟一天
真实耗时为 `24 / time_scale` 小时。情绪自然衰减固定按真实时间 1 Hz 执行，
不随倍率变化。
`timeContext.scale` 是基础连续倍率；`mode` 只保留旧倍率名称或输出 `custom`，
不参与计算。凌晨加速期间实际推进速度读取 `effectiveScale`。

任意 `1-100` 基础倍率均可选每日凌晨加速：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

- 每天虚拟 `00:00-06:00` 用36个虚拟10分钟步骤在30秒内走完。
- `06:00` 后同一时间节点恢复所选基础倍率，不退出、不重置情绪或行为结果状态。
- 下一天到达 `00:00` 后自动再次进入30秒凌晨加速。
- `timeContext.scale` 始终保持基础倍率；30秒加速期间
  `effectiveScale=720`，结束后恢复为基础倍率。
- 加速期间可以动态修改 `time_scale`，06:00 后按新倍率继续运行。
- 需求节点仍逐虚拟10分钟结算；情绪自然衰减仍按真实时间1 Hz。

凌晨睡眠流程也可单独压缩为30秒并在06:00结束：

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 random_seed:=12345
```

专用测试时间源从 `00:00` 到 `06:00` 发布36个 `TIME_TEST_STEP`，每步推进虚拟
10分钟。它会自动响应第一次 `NEED_SLEEPINESS_TRIGGERED`，发布
`ACTION_SLEEP + STARTED`；到达 `06:00` 后检查是否经历睡眠并最终醒来，然后
输出 `PASSED/FAILED` 并自动结束 launch。生产时间倍率范围仍为 `1-100`。

四类需求/情绪状态与事件消息均包含 `timeContext`。原顶层 `timestamp` 仍是真实
Unix 时间，`timeContext.virtualDateTime` 表示公式计算使用的虚拟时间。测试
移交步骤见 [time_compression_test_guide.md](time_compression_test_guide.md)。

运行中切换倍率：

```bash
ros2 param set /time_controller_node time_scale 7
ros2 param set /time_controller_node time_scale 24
ros2 param set /time_controller_node time_scale 100
ros2 param set /time_controller_node time_scale 1
```

模式切换由统一时间节点一次完成。虚拟时间连续，需求/情绪 Tick 进度、当前
需求值、情绪值和睡眠状态均保留。

也可以分别启动：

```bash
ros2 run marsdog_need_emotion personality_node
ros2 run marsdog_need_emotion time_controller_node
ros2 run marsdog_need_emotion internal_need_node
ros2 run marsdog_need_emotion emotion_engine_node
```

## 10. 当前缺口

- 真实 ROS2 runtime 仍需在目标环境完整验证。
- 当前仍使用 `std_msgs/String + JSON`，尚未定义正式 msg。
- 触摸事件 `EVT_TACTILE_*` 在配置中保留，但没有 topic 接入。
- `EVT_AUDIO_LOUD / EVT_AUDIO_WITH_HUMAN` 在配置中保留，但新版感知文档当前未提供对应输入。
