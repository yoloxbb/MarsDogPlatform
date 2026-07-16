# Marsdog 需求/情绪计算 ROS2 Topic 格式约定

本文档只说明当前需求、情绪、性格计算模块直接订阅或发布的 ROS2 Topic。

统一约定：

- 消息类型均为 `std_msgs/msg/String`。
- `data` 字段必须是 JSON 对象字符串。
- 所有状态值范围均为 `0-100`。
- 未知事件、非法 JSON、字段类型不符合要求时会被忽略，不更新状态。

## 1. Topic 总览

### 1.1 输入 Topic

| Topic | QoS | 订阅节点 | 用途 |
|---|---|---|---|
| `/perception/audio_event` | `RELIABLE, depth=10` | `internal_need_node`，`emotion_engine_node` | 声音事件输入 |
| `/perception/visual_event` | `BEST_EFFORT, depth=5` | `internal_need_node`，`emotion_engine_node` | 视觉事件输入 |
| `/behavior/result_event` | `RELIABLE, depth=10` | `internal_need_node`，`emotion_engine_node` | 行为结果输入 |
| `/personality/state` | `RELIABLE + TRANSIENT_LOCAL, depth=1` | `internal_need_node`，`emotion_engine_node` | 性格状态同步 |

### 1.2 输出 Topic

| Topic | QoS | 发布节点 | 发布规则 |
|---|---|---|---|
| `/personality/state` | `RELIABLE + TRANSIENT_LOCAL, depth=1` | `personality_node` | 启动时和性格变化后发布 |
| `/internal_need/state` | `RELIABLE, depth=10` | `internal_need_node` | 每 1 秒持续发布 |
| `/internal_need/signal_event` | `RELIABLE, depth=10` | `internal_need_node` | 需求等级变化时发布 |
| `/emotion/state` | `RELIABLE, depth=10` | `emotion_engine_node` | 每个虚拟秒发布；标准/12小时/2小时模式为真实 1/2/12 Hz |
| `/emotion/signal_event` | `RELIABLE, depth=10` | `emotion_engine_node` | 情绪区间或主导情绪变化时发布 |

## 2. 输入 Topic

### 2.1 `/perception/audio_event`

需求节点读取 `event_type`，目前只用以下事件更新需求上下文：

- `EVT_VOICE_MASTER_ID`
- `EVT_VOICE_CALL_NAME`

情绪节点读取 `event_type`，命中 `configs/emotions.yaml:eventRules` 时更新情绪值。

格式：

```json
{
  "event_type": "EVT_VOICE_PRAISE",
  "timestamp": 1710000000.0,
  "masterId": true,
  "metadata": {}
}
```

字段说明：

| 字段 | 要求 | 说明 |
|---|---|---|
| `event_type` | 必填 string | 声音事件名 |
| `timestamp` | 可选 number | 当前只透传，不参与计算 |
| `masterId` / `master_id` / `speakerIsMaster` | 可选 bool | `EVT_VOICE_PRAISE` 的主人声纹倍率字段 |
| 其他字段 | 可选 | 可作为事件倍率或扩展元数据 |

当前声音事件映射：

| event_type | 影响 |
|---|---|
| `EVT_VOICE_PRAISE` | 情绪事件 |
| `EVT_VOICE_SCOLD` | 情绪事件 |
| `EVT_VOICE_COMMAND_KNOWN` | 情绪事件 |
| `EVT_VOICE_COMMAND_UNKNOWN` | 情绪事件 |
| `EVT_VOICE_HAPPY` | 情绪事件 |
| `EVT_VOICE_SAD` | 情绪事件 |
| `EVT_VOICE_NEUTRAL` | 情绪事件 |
| `EVT_VOICE_CALL_NAME` | 情绪事件；需求节点标记主人出现 |
| `EVT_VOICE_MASTER_ID` | 情绪事件；需求节点标记主人出现 |
| `EVT_VOICE_STRANGER_ID` | 情绪事件 |

### 2.2 `/perception/visual_event`

情绪节点只读取 `events` 数组，逐个应用情绪事件映射。
需求节点目前只在 `events` 中出现 `EVT_VISION_MASTER` 时标记主人出现。

不会从 `faces / humans / hands / tracked_objects / active_target` 自动推断情绪事件。

格式：

```json
{
  "header": {
    "stamp": 1710000000.0,
    "frame_id": "camera_link"
  },
  "active_target": {
    "track_id": 1,
    "identity": "unknown",
    "confidence": 0.8
  },
  "faces": [],
  "humans": [],
  "hands": [],
  "tracked_objects": [],
  "events": [
    "EVT_VISION_MASTER"
  ]
}
```

字段说明：

| 字段 | 要求 | 说明 |
|---|---|---|
| `events` | 必填 list，可为空 | 视觉事件名数组；为空时不更新情绪 |
| `active_target` | 可选 object | 当前不直接参与需求/情绪计算 |
| `faces` | 可选 list | 当前不直接参与需求/情绪计算 |
| `humans` | 可选 list | 当前不直接参与需求/情绪计算 |
| `hands` | 可选 list | 当前不直接参与需求/情绪计算 |
| `tracked_objects` | 可选 list | 当前不直接参与需求/情绪计算 |

当前视觉事件映射：

| event_type | 影响 |
|---|---|
| `EVT_VISION_MASTER` | 情绪事件；需求节点标记主人出现 |
| `EVT_VISION_MASTER_HAPPY` | 情绪事件 |
| `EVT_VISION_MASTER_SAD` | 情绪事件 |
| `EVT_VISION_MASTER_NEUTRAL` | 情绪事件 |
| `EVT_VISION_STRANGER` | 情绪事件 |
| `EVT_VISION_STRANGER_ALERT` | 情绪事件 |
| `EVT_VISION_STRANGER_FRIEND` | 情绪事件 |
| `EVT_VISION_FOOD` | 情绪事件 |
| `EVT_VISION_TOY` | 情绪事件 |
| `EVT_VISION_FALL` | 情绪事件 |
| `EVT_VISION_STOP_GESTURE` | 情绪事件 |
| `EVT_VISION_HAND_TO_NOSE` | 情绪事件 |
| `EVT_VISION_HAND_TO_NOSE_FEAR` | 情绪事件 |
| `EVT_VISION_ANIMAL_CALM` | 情绪事件 |
| `EVT_VISION_ANIMAL_GREET` | 情绪事件 |
| `EVT_VISION_ANIMAL_PLAY` | 情绪事件 |
| `EVT_VISION_ANIMAL_BOUNDARY` | 情绪事件 |

### 2.3 `/behavior/result_event`

用于更新需求值和行为结果引起的情绪变化。

行为树节点对齐本 topic 的详细要求见 [behavior_result_event_alignment.md](behavior_result_event_alignment.md)。

格式：

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

字段说明：

| 字段 | 要求 | 说明 |
|---|---|---|
| `event_id` | 必填 string | 同一节点内重复 `event_id` 只处理一次 |
| `timestamp` | 建议填写 number | Unix 时间戳；当前只透传，不参与计算 |
| `action_type` | 必填 string | 必须是已登记的内部需求相关 `ACTION_*` |
| `demand_type` | 必填 string | 必须与 `action_type` 映射一致，否则拒绝处理 |
| `result_type` | 必填 string | 只接受 `STARTED / COMPLETED / FAILED / INTERRUPTED / CANCELLED / TIMEOUT` |
| `metadata` | 必填 object | 没有额外字段时传 `{}`；非 object 会被拒绝 |

当前接受的 `action_type -> demand_type`：

| action_type | demand_type |
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

`metadata` 约束：

| action_type | metadata |
|---|---|
| `ACTION_EAT` | `foodType=PremiumFood/NormalFood/Snack`，`portions` 为数字，`eatEfficiency=Full/HalfInterrupted` |
| `ACTION_RECHARGE` | `energyValue` 为 `0-100` 数字；兼容 `energy_value / batteryValue` |
| `ACTION_SOCIAL_*` | `socialOutcome=OwnerInteraction/DogHumanResponded/DogAnimalResponded/Rejected/TimedOut` |
| `ACTION_EXPLORE*` | 当前忽略 metadata |

`result_type` 对需求的影响：

| result_type | 需求处理 |
|---|---|
| `STARTED` | 仅 `ACTION_SLEEP` 会进入睡眠状态 |
| `COMPLETED` | 按 `action_type` 结算需求 |
| `FAILED` | 需求值不变 |
| `INTERRUPTED` | 对应需求按中断规则扣减 |
| `CANCELLED` | 对应需求按中断规则扣减 |
| `TIMEOUT` | 对应需求按中断规则扣减 |

`result_type` 对情绪的影响：

| result_type | 情绪映射 |
|---|---|
| `COMPLETED` | `DemandSatisfied` |
| `FAILED` | `DemandUnsatisfied` |
| `TIMEOUT` | `DemandUnsatisfied` |
| `INTERRUPTED` | `ActionInterrupted` |
| `CANCELLED` | `ActionInterrupted` |
| `STARTED` | 不影响情绪 |

### 2.4 `/personality/state`

`personality_node` 发布该 topic，需求节点和情绪节点订阅后同步本地性格参数。

格式：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "profile": "SunnyExplorer",
  "params": {
    "A": 90,
    "O": 80,
    "E": 95,
    "C": 70
  },
  "coefficients": {
    "Joy": 1.82,
    "Excite": 1.87,
    "Anxiety": 1.44,
    "Fear": 0.6,
    "Curious": 2.03,
    "Calm": 1.7,
    "Social": 1.82
  }
}
```

字段说明：

| 字段 | 要求 | 说明 |
|---|---|---|
| `profile` | 必填 string | `Custom / GentleCompanion / SunnyExplorer / LoyalGuardian / ProudIndependent` |
| `params` | 必填 object | 必须包含 `A/O/E/C`，且都是 `0-100` 整数 |
| `coefficients` | 输出字段 | 派生值，订阅侧不需要手动设置 |

性格修改入口是 ROS2 参数服务，不是 topic：

```bash
ros2 param set /personality_node profile SunnyExplorer
ros2 param set /personality_node A 85
ros2 param set /personality_node O 75
ros2 param set /personality_node E 30
ros2 param set /personality_node C 40
```

## 3. 输出 Topic

### 3.1 公共时间字段

`/internal_need/state`、`/internal_need/signal_event`、`/emotion/state` 和
`/emotion/signal_event` 均保留原有顶层 `timestamp`，其含义仍为消息生成时的
真实 Unix 时间。四类消息同时增加：

```json
{
  "timestamp": 1784157900.0,
  "timeContext": {
    "mode": "demo_2h",
    "scale": 12,
    "virtualStartDateTime": "2026-07-16T06:00:00+08:00",
    "virtualDateTime": "2026-07-16T14:30:00+08:00",
    "virtualTimestamp": 1784183400.0,
    "virtualElapsedSeconds": 30600.0,
    "wallTimestamp": 1784157900.0
  }
}
```

| 字段 | 说明 |
|---|---|
| `mode` | `standard_24h / demo_12h / demo_2h` |
| `scale` | 虚拟时间倍率 `1 / 2 / 12` |
| `virtualStartDateTime` | 本次进程的虚拟时间起点，ISO 8601 |
| `virtualDateTime` | 本条状态或事件对应的虚拟日期时间 |
| `virtualTimestamp` | 对应虚拟 Unix 时间戳 |
| `virtualElapsedSeconds` | 从虚拟起点累计经过的虚拟秒数 |
| `wallTimestamp` | 与顶层 `timestamp` 一致的真实 Unix 时间 |

需求和情绪的昼夜规则只读取 `virtualDateTime`。外部感知事件和行为结果仍在
收到时立即处理，不会因时间倍率而自动生成或延迟。

### 3.2 `/personality/state`

格式同 2.4。该 topic 使用 `TRANSIENT_LOCAL`，后启动的需求节点和情绪节点也能收到最近一次性格状态。

### 3.3 `/internal_need/state`

每 1 秒持续发布完整需求状态。

格式：

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

`demands` 固定包含：

- `Hunger`
- `Bladder`
- `Sleepiness`
- `Cleanliness`
- `Energy`
- `Social`
- `Exploration`

单个需求字段说明：

| 字段 | 说明 |
|---|---|
| `value` | 当前需求值 |
| `triggerThreshold` | 触发阈值 |
| `triggerOperator` | 触发比较符，如 `gt / lt` |
| `overflowThreshold` | 满溢阈值 |
| `triggered` | 是否超过触发阈值 |
| `overflow` | 是否超过满溢阈值 |
| `level` | `NORMAL / TRIGGERED / OVERFLOW` |
| `levelEvent` | 当前等级对应事件名 |
| `levelActive` | `level != NORMAL` |

顶层字段说明：

| 字段 | 说明 |
|---|---|
| `levelEvents` | 按需求名输出当前等级事件名 |
| `triggered` | 当前处于触发状态的需求列表 |
| `sleep` | 睡眠状态补充信息 |

对比规则：

```text
/internal_need/state.levelEvents[signal_event.demand] == /internal_need/signal_event.event_type
```

### 3.4 `/internal_need/signal_event`

需求等级变化时发布；同一等级不会重复发布。

格式：

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

字段说明：

| 字段 | 说明 |
|---|---|
| `event_type` | 需求等级事件名 |
| `demand` | 需求名 |
| `value` | 当前需求值 |
| `level` | 当前等级 |
| `previousLevel` | 上一次等级 |
| `trigger` | 固定为 `LEVEL_CHANGED` |

事件命名规则：

```text
NEED_<DEMAND>_RECOVERED
NEED_<DEMAND>_TRIGGERED
NEED_<DEMAND>_OVERFLOW
```

### 3.5 `/emotion/state`

每个虚拟秒发布完整情绪状态。三种模式对应真实发布频率为 `1 Hz / 2 Hz / 12 Hz`。

格式：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "emotions": {
    "Joy": {
      "value": 72,
      "triggerThreshold": 30,
      "triggerOperator": "gte",
      "triggered": true,
      "level": "MID",
      "levelEvent": "EMO_JOY_MID",
      "levelRange": [61, 85],
      "levelActive": true
    }
  },
  "levelEvents": {
    "Joy": "EMO_JOY_MID",
    "Excite": null,
    "Anxiety": null,
    "Fear": null,
    "Curious": null,
    "Calm": "EMO_CALM_NORMAL"
  },
  "triggered": [
    {
      "type": "Joy",
      "value": 72,
      "level": "MID",
      "eventType": "EMO_JOY_MID",
      "range": [61, 85],
      "triggerThreshold": 30,
      "triggerOperator": "gte"
    }
  ],
  "dominantEmotion": "Joy",
  "dominantEmotionSignal": {
    "emotion": "Joy",
    "value": 72,
    "level": "MID",
    "eventType": "EMO_JOY_MID",
    "range": [61, 85],
    "active": true
  },
  "personality": {
    "A": 50,
    "O": 50,
    "E": 50,
    "C": 50
  },
  "lastEmotionEventResult": {}
}
```

`emotions` 固定包含：

- `Joy`
- `Excite`
- `Anxiety`
- `Fear`
- `Curious`
- `Calm`

单个情绪字段说明：

| 字段 | 说明 |
|---|---|
| `value` | 当前情绪值 |
| `triggerThreshold` | 触发表达阈值 |
| `triggerOperator` | 触发比较符 |
| `triggered` | 是否达到触发阈值 |
| `level` | 当前强度区间名称；无区间时为 `NONE` |
| `levelEvent` | 当前区间事件名；无区间时为 `null` |
| `levelRange` | 当前区间范围；无区间时为 `null` |
| `levelActive` | 是否处于已定义区间 |

顶层字段说明：

| 字段 | 说明 |
|---|---|
| `levelEvents` | 按情绪名输出当前区间事件名 |
| `triggered` | 当前处于已定义强度区间的情绪列表 |
| `dominantEmotion` | 当前值最高的情绪 |
| `dominantEmotionSignal` | 主导情绪当前区间事件 |
| `personality` | 当前情绪系统同步到的 A/O/E/C |
| `lastEmotionEventResult` | 最近一次外部情绪事件计算结果 |

对比规则：

```text
/emotion/state.levelEvents[signal_event.emotion] == /emotion/signal_event.event_type
```

### 3.6 `/emotion/signal_event`

情绪区间变化或主导情绪变化时发布；同一状态不会重复发布。

格式：

```json
{
  "schema_version": "1.0",
  "timestamp": 1710000000.0,
  "event_type": "EMO_JOY_MID",
  "emotion": "Joy",
  "value": 72,
  "level": "MID",
  "range": [61, 85],
  "trigger": "LEVEL_CHANGED_AND_DOMINANT_CHANGED",
  "isDominant": true,
  "dominantChanged": true
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `event_type` | 情绪区间事件名 |
| `emotion` | 情绪名 |
| `value` | 当前情绪值 |
| `level` | 当前强度区间 |
| `range` | 当前区间范围 |
| `trigger` | `LEVEL_CHANGED / DOMINANT_CHANGED / LEVEL_CHANGED_AND_DOMINANT_CHANGED` |
| `isDominant` | 当前事件对应情绪是否为主导情绪 |
| `dominantChanged` | 主导情绪是否发生变化 |

当前情绪区间事件：

| 情绪 | 区间 | event_type |
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

## 4. 调试命令

标准模式启动三个节点：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py time_mode:=standard_24h
```

12 小时与 2 小时压缩模式：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py time_mode:=demo_12h
ros2 launch marsdog_behavior internal_need_emotion.launch.py time_mode:=demo_2h
```

固定起点与随机种子：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py \
  time_mode:=demo_2h virtual_start_time:=06:00 random_seed:=12345
```

`time_mode`、`virtual_start_time` 和 `random_seed` 都是启动后只读参数。压缩模式
的 `virtual_start_time:=auto` 等价于当天 `06:00`；标准模式的 `auto` 从当前真实
时间开始。详细全天测试步骤见
[time_compression_test_guide.md](time_compression_test_guide.md)。

查看输出：

```bash
ros2 topic echo /personality/state --field data
ros2 topic echo /internal_need/state --field data
ros2 topic echo /internal_need/signal_event --field data
ros2 topic echo /emotion/state --field data
ros2 topic echo /emotion/signal_event --field data
```

发布行为结果示例：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String "{data: '{\"event_id\":\"result-test-001\",\"action_type\":\"ACTION_EAT\",\"demand_type\":\"Hunger\",\"result_type\":\"COMPLETED\",\"metadata\":{\"foodType\":\"NormalFood\",\"portions\":1,\"eatEfficiency\":\"Full\"}}'}"
```

发布声音事件示例：

```bash
ros2 topic pub --once /perception/audio_event std_msgs/msg/String "{data: '{\"event_type\":\"EVT_VOICE_PRAISE\",\"masterId\":true}'}"
```

发布视觉事件示例：

```bash
ros2 topic pub --once /perception/visual_event std_msgs/msg/String "{data: '{\"events\":[\"EVT_VISION_TOY\"]}'}"
```
