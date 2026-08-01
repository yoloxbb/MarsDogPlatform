# Marsdog 需求/情绪计算 ROS2 Topic 格式约定

本文档只说明当前需求、情绪、性格计算模块直接订阅或发布的 ROS2 Topic。
内部需求 V1 订阅方升级到 V2 时，请同时阅读
[内部需求 V2 联调迁移说明](2026-07-29_internal_need_v2_integration_guide.md)。

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
| `/perception/tactile_event` | `RELIABLE, depth=10` | `internal_need_node`，`emotion_engine_node` | 触觉事件输入；当前由 ONE1000 适配节点发布摸头事件 |
| `/behavior/result_event` | `RELIABLE, depth=10` | `internal_need_node`，`emotion_engine_node` | 行为结果输入 |
| `/personality/state` | `RELIABLE + TRANSIENT_LOCAL, depth=1` | `internal_need_node`，`emotion_engine_node` | 性格状态同步 |
| `/simulation/time_state` | `RELIABLE + TRANSIENT_LOCAL, depth=1000` | `internal_need_node`，`emotion_engine_node` | 权威虚拟时间和逐秒 Tick |

### 1.2 输出 Topic

| Topic | QoS | 发布节点 | 发布规则 |
|---|---|---|---|
| `/personality/state` | `RELIABLE + TRANSIENT_LOCAL, depth=1` | `personality_node` | 启动时和性格变化后发布 |
| `/simulation/time_state` | `RELIABLE + TRANSIENT_LOCAL, depth=1000` | `time_controller_node`；测试时为 `midnight_test_node` | 初始化、逐虚拟秒 Tick、倍率变化或测试跳步 |
| `/internal_need/state` | `RELIABLE, depth=10` | `internal_need_node` | 每 1 秒持续发布 |
| `/internal_need/signal_event` | `RELIABLE, depth=10` | `internal_need_node` | 需求等级变化时发布 |
| `/emotion/state` | `RELIABLE, depth=10` | `emotion_engine_node` | 每个虚拟秒发布；真实频率为 `time_scale` Hz |
| `/emotion/signal_event` | `RELIABLE, depth=10` | `emotion_engine_node` | 情绪首次达到触发阈值时发布 |
| `/simulation/midnight_test_result` | `RELIABLE + TRANSIENT_LOCAL, depth=1` | `midnight_test_node` | 凌晨测试完成时发布 `PASSED/FAILED` 和最终状态 |
| `/perception/tactile_event` | `RELIABLE, depth=10` | `one1000_tactile_node` | ONE1000 摸头状态从未触摸变为触摸时发布 |
| `/one1000/status` | `RELIABLE, depth=10` | `one1000_tactile_node` | 真实时间 1 Hz 发布串口、C5距离、雷达和摸头诊断状态 |

情绪自然衰减由 `emotion_engine_node` 的单调真实时钟以 1 Hz 驱动，不依赖
`/simulation/time_state` 的虚拟 Tick 频率，也不随 `time_scale` 加速。
当前只有 `Joy / Excite / Fear / Curious` 自然衰减，`Anxiety / Calm` 不随
时间变化，但仍可由输入事件和行为结果修改。

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

### 2.3 `/perception/tactile_event`

触觉事件使用单个 `event_type`。情绪节点命中
`configs/emotions.yaml:eventRules` 时更新情绪；需求节点接收事件但当前不修改需求值。

ONE1000 临时适配节点当前只发布摸头事件。默认使用 C5 信标距离，小于10cm时
发布：

```json
{
  "schema_version": "1.0",
  "timestamp": 1785556800.0,
  "event_type": "EVT_TACTILE_HEAD_PET",
  "source": "ONE1000",
  "sensorType": "UWB_DISTANCE",
  "touchState": "STARTED",
  "detectionMethod": "DISTANCE_THRESHOLD",
  "distanceMeters": 0.075,
  "distanceCentimeters": 7.5,
  "distanceThresholdCentimeters": 10.0,
  "anchorMacId": 287454020,
  "beaconId": 1432778632,
  "beaconType": 2,
  "positionConfidence": 95
}
```

| 字段 | 要求 | 说明 |
|---|---|---|
| `event_type` | 必填 string | 当前 ONE1000 固定为 `EVT_TACTILE_HEAD_PET` |
| `timestamp` | 必填 number | 传感器事件产生时的真实 Unix 时间 |
| `source` | 必填 string | ONE1000 节点固定为 `ONE1000` |
| `sensorType` | 必填 string | 距离模式为 `UWB_DISTANCE`，雷达模式为 `UWB_RADAR` |
| `touchState` | 必填 string | 每次摸头事件固定为 `STARTED` |
| `distanceMeters / distanceCentimeters` | 距离模式字段 | C5 原始米制距离及其厘米换算值 |
| `distanceThresholdCentimeters` | 距离模式字段 | 启动时配置的严格小于阈值，默认10cm |
| `anchorMacId / beaconId / beaconType` | 距离模式字段 | C5 基站和信标标识 |
| `rawStatus` | 调试字段 | ONE1000 `0x54` 原始状态位；bit0 为活体，bit1 为摸头 |
| `livingBodyDetected` | 调试字段 | 是否同时检测到活体 |
| `maxRadarValue` | 调试字段 | 厂商协议提供的雷达调试值，不参与情绪计算 |
| `livingBodyFirstIndex` | 调试字段 | 厂商协议提供的活体首次位置索引，不参与情绪计算 |

距离模式在有效距离满足 `0 < distance < 10cm` 时首次发布；0米按无效测距
处理，恰好10cm不触发。持续保持在阈值内时，每经过
`touch_cooldown_seconds` 再发布一次，默认间隔2秒；离开阈值后停止。雷达模式
保持原有摸头位上升沿规则。重复间隔使用真实时间，不受
`time_scale` 或凌晨加速影响。默认性格下每次
`EVT_TACTILE_HEAD_PET` 使 `Joy +25 / Calm +15 / Excite +5`。初始 Joy 为0，
因此第一次摸头不会达到 Joy 的30阈值；信标持续保持在10cm内，默认2秒后第二次
事件会让 Joy 在真实时间衰减后再次增加25并越过阈值，发布
`EMO_JOY_TRIGGERED`。

### 2.4 `/behavior/result_event`

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
| `ACTION_RECHARGE` | `energyValue` 为充电后的 `0-100` 电量百分比；兼容 `energy_value / batteryValue`，内部保存 `Energy=100-energyValue` |
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

### 2.5 `/personality/state`

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

### 2.6 `/simulation/time_state`

生产运行时 `time_controller_node` 是唯一权威虚拟时间源。`time_scale` 允许
`1-100` 整数，需求和情绪节点只消费本 Topic，不再各自使用需求自然更新定时器。
专用 `midnight_test.launch.py` 不启动生产时间节点，改由测试节点发布离散
`TIME_TEST_STEP`。

```json
{
  "schema_version": "1.0",
  "timestamp": 1784157900.0,
  "event_type": "TIME_TICK",
  "tickSequence": 30600,
  "timeContext": {
    "mode": "demo_2h",
    "scale": 12,
    "revision": 1,
    "virtualStartDateTime": "2026-07-16T06:00:00+08:00",
    "virtualDateTime": "2026-07-16T14:30:00+08:00",
    "virtualTimestamp": 1784183400.0,
    "virtualElapsedSeconds": 30600.0,
    "wallTimestamp": 1784157900.0
  }
}
```

| `event_type` | 说明 | 是否执行自然更新 |
|---|---|---|
| `TIME_INITIALIZED` | 权威时钟启动 | 否 |
| `TIME_TICK` | 一个虚拟秒到期 | 是 |
| `TIME_MODE_CHANGED` | 运行中倍率切换完成；事件名为兼容保留 | 否 |
| `TIME_TEST_STEP` | 仅凌晨测试使用；一次推进虚拟10分钟 | 是 |
| `TIME_ACCELERATION_CHANGED` | 每日凌晨加速开始或结束 | 否 |
| `TIME_ACCELERATED_STEP` | 连续运行模式的凌晨加速步骤；一次推进虚拟10分钟 | 是 |

生产时间节点的 `tickSequence` 对普通 `TIME_TICK` 增加1，对
`TIME_ACCELERATED_STEP` 增加600。凌晨测试的
`tickSequence` 为 `0-36`，消息额外包含 `testScenario`，其中
`effectiveTimeScale=720` 表示30秒测试的等效压缩率。`timeContext.scale`
在独立测试时间源中固定为24；时间跳变由 `TIME_TEST_STEP` 明确表达。

统一时间节点启用每日凌晨加速时，`timeContext` 增加：

```json
{
  "scale": 100,
  "effectiveScale": 720.0,
  "midnightAcceleration": {
    "enabled": true,
    "active": true,
    "durationSeconds": 30.0,
    "virtualStepSeconds": 600,
    "stepSequence": 1,
    "stepCount": 36
  }
}
```

`effectiveScale` 在加速活动期间为 `21600 / durationSeconds`，06:00后恢复
为当前基础倍率。需求和情绪输出会保留这些字段。`scale` 始终表示
`1-100` 范围内的基础连续倍率，加速期间也允许动态切换。

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
    "revision": 1,
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
| `mode` | 兼容显示字段：倍率 `1/2/12` 使用旧名称，其他倍率为 `custom`；不参与计算 |
| `scale` | 基础连续虚拟时间倍率，`1-100` 整数 |
| `effectiveScale` | 可选；启用凌晨加速时表示当前实际推进倍率，非活动阶段等于 `scale` |
| `midnightAcceleration` | 可选的每日凌晨加速配置、活动状态和步骤进度 |
| `revision` | 倍率配置修订号，启动为 0，每次实际切换增加 1 |
| `virtualStartDateTime` | 本次进程的虚拟时间起点，ISO 8601 |
| `virtualDateTime` | 本条状态或事件对应的虚拟日期时间 |
| `virtualTimestamp` | 对应虚拟 Unix 时间戳 |
| `virtualElapsedSeconds` | 从虚拟起点累计经过的虚拟秒数 |
| `wallTimestamp` | 与顶层 `timestamp` 一致的真实 Unix 时间 |

需求和情绪的昼夜规则只读取 `virtualDateTime`。外部感知事件和行为结果仍在
收到时立即处理，不会因时间倍率而自动生成或延迟。

### 3.2 `/personality/state`

格式同 2.5。该 topic 使用 `TRANSIENT_LOCAL`，后启动的需求节点和情绪节点也能收到最近一次性格状态。

### 3.3 `/internal_need/state`

每 1 秒持续发布完整需求状态。

格式：

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

`demands` 固定包含：

- `Hunger`
- `Bladder`
- `Sleepiness`
- `Cleanliness`
- `Energy`
- `Social`
- `Exploration`

其中 `Energy` 表示充电需求/电量缺口，计算公式为
`Energy = 100 - 当前电量百分比`。因此所有需求都保持“数值越高越紧急”。
节点每次启动时模拟电量为 `100%`。满电续航为 2 个虚拟小时，Energy 每
10 个虚拟分钟结算一次自然耗电；睡眠和普通需求锁定不会暂停耗电。普通时段
`time_scale=S` 时，满电耗尽对应 `7200/S` 秒真实时间。

凌晨特殊加速期间采用单独口径：每个 `TIME_ACCELERATED_STEP` 或
`TIME_TEST_STEP` 仍驱动其他需求走完对应的虚拟10分钟，但 Energy 只累计
`durationSeconds / stepCount` 秒。默认30秒、36步时，每步只累计约
`0.8333` 秒，整个虚拟 `00:00-06:00` 仅按1倍衰减30秒。每天06:00的晨起
需求重置不恢复电量。

单个需求字段说明：

| 字段 | 说明 |
|---|---|
| `value` | 当前需求值 |
| `triggerThreshold` | 触发阈值 |
| `triggerOperator` | 触发比较符，如 `gt / lt` |
| `urgentThreshold` | 可选的中间紧急阈值；未配置时为 `null` |
| `urgentOperator` | 可选的中间紧急比较符；未配置时为 `null` |
| `overflowThreshold` | 可选的满溢阈值；未配置时为 `null` |
| `triggered` | 是否超过触发阈值 |
| `urgent` | 是否超过中间紧急阈值；未配置时为 `false` |
| `overflow` | 是否超过满溢阈值 |
| `level` | `NORMAL / TRIGGERED / URGENT / OVERFLOW` |
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

当前需求等级区间：

| 需求 | NORMAL | TRIGGERED | URGENT | OVERFLOW |
|---|---|---|---|---|
| `Hunger` | `0-70` | `71-90` | 无 | `91-100` |
| `Bladder` | `0-75` | `76-100` | 无 | 无 |
| `Sleepiness` | `0-65` | `66-90` | 无 | `91-100` |
| `Cleanliness` | `0-70` | `71-100` | 无 | 无 |
| `Energy` | `0-80` | `81-90` | 无 | `91-100` |
| `Social` | `0-60` | `61-70` | `71-85` | `86-100` |
| `Exploration` | `0-60` | `61-100` | 无 | 无 |

### 3.4 `/internal_need/signal_event`

需求等级变化时发布；同一等级不会重复发布。

格式：

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

字段说明：

| 字段 | 说明 |
|---|---|
| `event_type` | 需求等级事件名 |
| `demand` | 需求名 |
| `value` | 当前需求值 |
| `level` | 当前等级 |
| `previousLevel` | 上一次等级 |
| `triggerThreshold / triggerOperator` | 首次触发线及比较符 |
| `urgentThreshold / urgentOperator` | 可选的中间紧急线及比较符 |
| `overflowThreshold / overflowOperator` | 可选的满溢线及比较符 |
| `trigger` | 固定为 `LEVEL_CHANGED` |

事件命名规则：

```text
NEED_<DEMAND>_RECOVERED
NEED_<DEMAND>_TRIGGERED
NEED_<DEMAND>_URGENT
NEED_<DEMAND>_OVERFLOW
```

当前只有 Social 会发布 `NEED_SOCIAL_URGENT`。Bladder、Cleanliness 和
Exploration 未配置满溢线，到 `100` 时仍保持 `TRIGGERED`，不会发布满溢事件。

### 3.5 `/emotion/state`

每个虚拟秒发布完整情绪状态，真实发布频率为 `time_scale` Hz。该频率只影响
状态发布时间线；配置了衰减速率的情绪固定按真实时间 1 Hz 计算，
`Anxiety / Calm` 不自然衰减。该 Topic 使用 `schema_version=2.0`。

格式：

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "emotions": {
    "Joy": {
      "value": 72,
      "triggerThreshold": 30,
      "triggerOperator": "gte",
      "triggered": true
    }
  },
  "triggered": [
    {
      "emotion": "Joy",
      "value": 72,
      "eventType": "EMO_JOY_TRIGGERED",
      "triggerThreshold": 30,
      "triggerOperator": "gte"
    }
  ],
  "dominantEmotion": "Joy",
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

顶层字段说明：

| 字段 | 说明 |
|---|---|
| `triggered` | 当前达到单一阈值的情绪列表 |
| `dominantEmotion` | 当前值最高的情绪 |
| `personality` | 当前情绪系统同步到的 A/O/E/C |
| `lastEmotionEventResult` | 最近一次外部情绪事件计算结果 |

情绪层级、区间和主导情绪信号字段已从 V2 删除。`dominantEmotion` 只表示当前
数值最大项，不参与触发事件生成。

Calm 是兜底状态。只有 Joy、Excite、Anxiety、Fear、Curious 全部未触发时，
`emotions.Calm.triggered=true` 且 `triggered[]` 包含 Calm；任一其他情绪达到
阈值时，Calm 立即退出触发状态。Calm 消息仍保留配置字段
`triggerThreshold=0` 和 `triggerOperator=gte`。

### 3.6 `/emotion/signal_event`

Joy、Excite、Anxiety、Fear、Curious 只在未触发变为已触发时发布。触发后
继续升高或主导情绪变化不会重复发布；降到阈值以下不发布恢复事件，但允许以后
再次达到阈值时重新触发。Calm 是例外：没有其他触发情绪时按真实时间 1 Hz
持续发布；任一其他情绪触发时停止，全部回落后恢复发布。该频率不受
`time_scale` 影响。

格式：

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "event_type": "EMO_JOY_TRIGGERED",
  "emotion": "Joy",
  "value": 72,
  "triggerThreshold": 30,
  "triggerOperator": "gte"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `event_type` | `EMO_<EMOTION>_TRIGGERED` |
| `emotion` | 情绪名 |
| `value` | 当前情绪值 |
| `triggerThreshold` | 本情绪的触发阈值 |
| `triggerOperator` | 本情绪的触发比较符 |

当前情绪触发事件：

| 情绪 | 触发条件 | event_type |
|---|---|---|
| `Calm` | 其他五种情绪均未触发 | `EMO_CALM_TRIGGERED`；平静期间真实时间 1 Hz 持续发布 |
| `Joy` | `>=30` | `EMO_JOY_TRIGGERED` |
| `Excite` | `>=40` | `EMO_EXCITE_TRIGGERED` |
| `Anxiety` | `>=25` | `EMO_ANXIETY_TRIGGERED` |
| `Fear` | `>=30` | `EMO_FEAR_TRIGGERED` |
| `Curious` | `>=20` | `EMO_CURIOUS_TRIGGERED` |

### 3.7 `/one1000/status`

ONE1000 节点按真实时间 1 Hz 持续发布诊断状态，不受 `time_scale` 或凌晨加速
影响。该 Topic 用于判断节点和硬件是否存活；业务摸头事件仍只从
`/perception/tactile_event` 获取。

```json
{
  "schema_version": "1.0",
  "timestamp": 1785563000.0,
  "source": "ONE1000",
  "serialPort": "/dev/ttyUSB1",
  "serialOpen": true,
  "connected": true,
  "detection": {
    "mode": "distance",
    "distanceThresholdCentimeters": 10.0,
    "distanceTouchActive": true
  },
  "protocol": {
    "active": true,
    "uartActive": true,
    "receivedByteCount": 1459,
    "lastByteAgeSeconds": 0.05,
    "validPacketCount": 31,
    "positionPacketCount": 31,
    "lastPacketAgeSeconds": 0.1
  },
  "commands": {
    "startupCommandsQueued": false,
    "sentCount": 0,
    "responseCount": 0,
    "lastResponse": null
  },
  "heartbeat": {
    "counter": 42,
    "ageSeconds": 0.2,
    "rangingStatus": 6,
    "rangingState": "TIMEOUT",
    "radarStatus": 5,
    "radarState": "ACTIVE",
    "radarActive": true
  },
  "sentryStatus": null,
  "position": {
    "ageSeconds": 0.02,
    "anchorMacId": 287454020,
    "beaconId": 1432778632,
    "distanceMeters": 0.08,
    "distanceCentimeters": 8.0,
    "withinTouchThreshold": true
  }
}
```

| 字段 | 说明 |
|---|---|
| `serialOpen` | 节点是否仍持有串口 |
| `connected` | 串口已打开，且最近2.5秒内收到过 UART 字节、有效协议包或心跳 |
| `detection.mode` | `distance` 使用 C5 距离；`radar` 使用厂商 0x54 摸头位 |
| `detection.distanceTouchActive` | 最近有效距离是否严格小于配置阈值 |
| `protocol.uartActive` | 最近2.5秒内是否收到过任意 UART 字节，包括调试文本 |
| `protocol.active` | 最近2.5秒内是否收到通过外层长度和 CRC 校验的数据包 |
| `protocol.receivedByteCount` | 本次节点运行累计读取的 UART 字节数 |
| `protocol.validPacketCount` | 通过外层协议校验的数据包数 |
| `protocol.positionPacketCount` | 收到的 `0xC5` UWB 定位包数 |
| `position` | 最近一次解析成功的 C5 定位；尚未收到时为 `null` |
| `position.distanceCentimeters` | 信标到基站的当前厘米距离 |
| `position.withinTouchThreshold` | 当前有效距离是否满足严格小于阈值 |
| `commands.sentCount / responseCount` | 主机已发送命令数和设备 `0x00` 响应数 |
| `commands.lastResponse` | 最近命令响应；未收到任何响应时为 `null` |
| `heartbeat` | 最近心跳；尚未收到时为 `null` |
| `heartbeat.radarState` | `DEINITIALIZED / ACTIVE / RANGING_CONFLICT_TIMEOUT / UNKNOWN` |
| `heartbeat.radarActive` | `radarStatus == 0x05` |
| `sentryStatus` | 最近一次 `0x54` 结果；尚未收到时为 `null` |
| `sentryStatus.headTouchDetected` | 厂商原始摸头 bit1；事件边沿判断前的直接状态 |
| `ageSeconds` | 该硬件数据距本条诊断消息的真实秒数 |

部分 5.1.x 固件会把 `0xC5` Value 内层长度错误填写为33，但外层实际携带38字节，
总长度和 CRC 正确。适配节点只对 `C5 + 声明33 + 实际38` 这一精确组合兼容，
其他长度异常仍拒绝。默认 `distance` 模式不会发送哨兵命令，避免雷达模式切断
C5 定位流；只有显式选择 `radar` 模式后，节点才会在收到心跳或等待500ms后
发送设置阈值、清缓存和启动哨兵命令。
另有调试固件在哨兵活动期输出 `session cmd deinit / cir Ready` 文本而不是标准
`0x54/0x59`：此时 `connected=true`、`uartActive=true`，但
`protocol.active=false`，表示物理串口在线但业务协议不兼容。

诊断命令：

```bash
ros2 topic hz /one1000/status
ros2 topic echo /one1000/status --field data
```

## 4. 调试命令

1 倍启动四个节点：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py time_scale:=1
```

任意整数倍率启动：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py time_scale:=7
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py time_scale:=100
```

固定起点与随机种子：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 virtual_start_time:=06:00 random_seed:=12345
```

30秒凌晨场景测试：

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 random_seed:=12345
```

测试节点自动发送睡眠开始结果，到达虚拟 `06:00` 后输出
`Midnight test PASSED/FAILED` 并结束整个 launch。测试结果也会发布到
`/simulation/midnight_test_result`。

任意基础倍率连续联调并在06:00后恢复该倍率：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 \
  virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

`midnight_acceleration_enabled=true` 支持全部 `1-100` 基础倍率，运行时也可
切换倍率；如果在凌晨加速期间切换，06:00 后按新倍率继续运行。该模式不模拟
行为结果，外部行为模块需要处理睡眠信号。

运行中切换倍率：

```bash
ros2 param set /time_controller_node time_scale 7
ros2 param set /time_controller_node time_scale 24
ros2 param set /time_controller_node time_scale 100
ros2 param set /time_controller_node time_scale 1
```

只有 `/time_controller_node.time_scale` 支持运行时修改。`virtual_start_time` 和
`random_seed` 仍只能在启动时设置。倍率 2-100 的 `virtual_start_time:=auto`
等价于当天 `06:00`；倍率 1 的 `auto` 从当前真实时间开始。倍率切换不会修改虚拟
起点、需求值、情绪值或睡眠状态。详细测试步骤见
[time_compression_test_guide.md](time_compression_test_guide.md)。

查看输出：

```bash
ros2 topic echo /personality/state --field data
ros2 topic echo /simulation/time_state --field data
ros2 topic echo /internal_need/state --field data
ros2 topic echo /internal_need/signal_event --field data
ros2 topic echo /emotion/state --field data
ros2 topic echo /emotion/signal_event --field data
ros2 topic echo /one1000/status --field data
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
