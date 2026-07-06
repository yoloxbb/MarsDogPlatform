# Marsdog 当前实现总结

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
| `marsdog_core/*_behavior.py` | 各需求的数值增长、恢复和结果结算逻辑 |
| `marsdog_ros2/internal_need_node.py` | 发布 `/internal_need/state` 和 `/internal_need/signal_event` |
| `marsdog_ros2/emotion_engine_node.py` | 发布 `/emotion/state` 和 `/emotion/signal_event` |
| `marsdog_ros2/personality_node.py` | 维护性格参数并发布 `/personality/state` |
| `marsdog_ros2/perception_adapter.py` | 适配 `/perception/audio_event`、`/perception/visual_event` |
| `marsdog_ros2/behavior_result_adapter.py` | 适配 `/behavior/result_event` |
| `marsdog_ros2/personality_adapter.py` | 适配 `/personality/state` |
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

本层不调用感知服务，不主动请求找人、找物或动物识别。

### 输出

| Topic | 类型 | 节点 | 说明 |
|---|---|---|---|
| `/internal_need/state` | `std_msgs/String` JSON | `internal_need_node` | 全量内部需求状态，1 秒持续发布 |
| `/internal_need/signal_event` | `std_msgs/String` JSON | `internal_need_node` | 需求等级变化时发布 |
| `/emotion/state` | `std_msgs/String` JSON | `emotion_engine_node` | 全量情绪状态，1 秒持续发布 |
| `/emotion/signal_event` | `std_msgs/String` JSON | `emotion_engine_node` | 情绪区间或主导情绪变化时发布 |
| `/personality/state` | `std_msgs/String` JSON | `personality_node` | 性格状态，启动时和性格变化后发布 |

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
- 白天 `06:00-21:00`：每 Tick `+3`。
- 夜晚 `21:00-00:00`：每 Tick `+5`。
- 凌晨 `00:00-06:00` 或关灯：清醒状态下 `Sleepiness = 90`。
- 触发：`>65`。
- 满溢：`>90`。
- `ACTION_SLEEP + STARTED`：进入浅睡。
- 浅睡固定 3 Tick，每 Tick `-2`。
- 浅睡结束后仍 `>65` 则进入深睡，否则醒来。
- 深睡每 Tick `-15`，直到 `<=20` 自然醒来。
- `00:00-06:00` 强制睡眠期间不会自然醒。

### Cleanliness

- 晨起：`5-15`。
- 白天 `06:00-21:00`：每 Tick `+2`。
- 其他时间：`+0`。
- 触发：`>70`。
- 满溢：`>90`。
- 进食完成：`+20`。
- `ACTION_GROOM + COMPLETED`：`Cleanliness -= 50`。

### Energy

- 当前实现直接等于电池百分比。
- 晨起：`100`。
- 触发：`<20`。
- 满溢：`<10`。
- `ACTION_RECHARGE + COMPLETED`：
  - 有 `metadata.energyValue` 时写入该值。
  - 没有时恢复到 `100`。

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
- 白天 `06:00-21:00` 且 `Energy > 50`：每 Tick `+5`。
- 其他时间或精力不足：`+0`。
- 触发：`>60`。
- 满溢：`>80`。
- `ACTION_EXPLORE* + COMPLETED` 根据 `metadata.discoveryType` 结算：
  - `New`：`-20`
  - `Old`：`-10`
  - `Completed`：`-15`

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

情绪节点每 1 秒执行一次：

- `Joy -= 2/sec`
- `Excite -= 3/sec`
- `Anxiety -= 1.5/sec`
- `Fear -= 4/sec`
- `Curious -= 2/sec`
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

`/behavior/result_event` 示例：

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

`result_type` 支持：

- `STARTED`
- `COMPLETED`
- `FAILED`
- `INTERRUPTED`
- `CANCELLED`
- `TIMEOUT`

需求节点处理：

- `COMPLETED`：按 action 类型结算对应需求。
- `STARTED + ACTION_SLEEP`：进入睡眠状态。
- `INTERRUPTED / CANCELLED / TIMEOUT`：按对应需求扣减。
- `FAILED`：需求值不变。

情绪节点处理：

- `COMPLETED` -> `DemandSatisfied`
- `FAILED / TIMEOUT` -> `DemandUnsatisfied`
- `INTERRUPTED / CANCELLED` -> `ActionInterrupted`

## 9. 运行方式

Python 单元测试：

```bash
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

ROS2 节点：

```bash
ros2 run marsdog_behavior personality_node
ros2 run marsdog_behavior internal_need_node
ros2 run marsdog_behavior emotion_engine_node
```

## 10. 当前缺口

- 真实 ROS2 runtime 仍需在目标环境完整验证。
- 当前仍使用 `std_msgs/String + JSON`，尚未定义正式 msg。
- 触摸事件 `EVT_TACTILE_*` 在配置中保留，但没有 topic 接入。
- `EVT_AUDIO_LOUD / EVT_AUDIO_WITH_HUMAN` 在配置中保留，但新版感知文档当前未提供对应输入。
- 探索已知目标当前只保存在内存，不做持久化。
