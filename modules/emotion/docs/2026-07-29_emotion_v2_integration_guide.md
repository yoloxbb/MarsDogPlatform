# Marsdog 情绪 V2 联调迁移指南

## 1. 文档用途

本文面向行为模块和其他 `/emotion/*` Topic 使用方，用于从旧的情绪分级协议
迁移到当前单一阈值协议。

本次只修改情绪输出协议：

- `/emotion/state`
- `/emotion/signal_event`

需求、时间、性格、感知输入和行为结果协议不变。情绪状态和信号的
`schema_version` 已升级为 `2.0`，不兼容旧的情绪 V1 层级字段。

## 2. 必须修改的内容

### 2.1 事件名

旧的低、中、高等级事件全部合并为单一触发事件：

| 情绪 | 触发条件 | V2 事件名 |
|---|---:|---|
| `Joy` | `>=30` | `EMO_JOY_TRIGGERED` |
| `Excite` | `>=40` | `EMO_EXCITE_TRIGGERED` |
| `Anxiety` | `>=25` | `EMO_ANXIETY_TRIGGERED` |
| `Fear` | `>=30` | `EMO_FEAR_TRIGGERED` |
| `Curious` | `>=20` | `EMO_CURIOUS_TRIGGERED` |
| `Calm` | 其他五种情绪均未触发 | `EMO_CALM_TRIGGERED`，平静期间真实时间 1 Hz 持续发布 |

例如原来监听以下事件：

```text
EMO_JOY_LOW
EMO_JOY_MID
EMO_JOY_HIGH
```

现在统一监听：

```text
EMO_JOY_TRIGGERED
```

### 2.2 删除的字段

以下情绪字段已经删除，订阅方不得继续读取：

```text
level
levelEvent
levelRange
levelActive
levelEvents
dominantEmotionSignal
range
trigger
isDominant
dominantChanged
```

`triggered[]` 列表中的情绪字段也从旧版 `type` 改为 `emotion`。

### 2.3 触发规则

普通情绪的 `/emotion/signal_event` 表示阈值上升沿：

```text
未触发 false → 已触发 true：发布一次事件
已触发 true → 更高数值：不发布
已触发 true → 未触发 false：不发布恢复事件
未触发 false → 再次触发 true：重新发布一次事件
主导情绪变化：不发布
```

Calm 是例外。Joy、Excite、Anxiety、Fear、Curious 均未触发时，节点按真实时间
1 Hz 持续发布 `EMO_CALM_TRIGGERED`；任一其他情绪触发时停止，全部回落后恢复
发布。感知或行为结果到达时也会立即检查，因此平静状态下可能额外即时收到一条
Calm。该频率不受 `time_scale` 影响。

如果行为模块需要知道情绪是否已经恢复，必须读取
`/emotion/state.emotions.<name>.triggered`，不能等待恢复事件。

## 3. `/emotion/state` V2

消息类型仍为 `std_msgs/msg/String`，`data` 是 JSON 字符串。

示例：

```json
{
  "schema_version": "2.0",
  "timestamp": 1785290000.0,
  "emotions": {
    "Joy": {
      "value": 30,
      "triggerThreshold": 30,
      "triggerOperator": "gte",
      "triggered": true
    },
    "Excite": {
      "value": 20,
      "triggerThreshold": 40,
      "triggerOperator": "gte",
      "triggered": false
    }
  },
  "triggered": [
    {
      "emotion": "Joy",
      "value": 30,
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
  "lastEmotionEventResult": {},
  "timeContext": {}
}
```

说明：

- 实际消息固定包含六种情绪；示例只展开了其中两种。
- `dominantEmotion` 仍表示当前数值最大的情绪，但不触发信号事件。
- `triggered[]` 是当前状态集合，不是本次新增事件列表。
- `Calm` 只有在其他五种情绪均未触发时才位于 `triggered[]`；Joy 示例中不会
  同时包含 Calm。
- Calm 的 V2 字段仍显示 `triggerThreshold=0 / triggerOperator=gte`，但
  `triggered` 状态使用兜底条件判断。
- `/emotion/state` 每个虚拟秒发布，消费方应把它当作当前权威状态。

## 4. `/emotion/signal_event` V2

示例：

```json
{
  "schema_version": "2.0",
  "timestamp": 1785290000.0,
  "event_type": "EMO_JOY_TRIGGERED",
  "emotion": "Joy",
  "value": 30,
  "triggerThreshold": 30,
  "triggerOperator": "gte",
  "timeContext": {}
}
```

该 Topic 不提供恢复、高等级或主导情绪变化事件。普通情绪只发布新触发；Calm
在没有其他触发情绪时持续发布：

```json
{
  "schema_version": "2.0",
  "event_type": "EMO_CALM_TRIGGERED",
  "emotion": "Calm",
  "value": 30,
  "triggerThreshold": 0,
  "triggerOperator": "gte"
}
```

## 5. 订阅代码修改示例

```python
import json


def HandleEmotionStateMessage(message) -> dict:
    """解析 V2 情绪状态并返回各情绪的触发布尔值。"""
    payload = json.loads(message.data)
    if payload.get("schema_version") != "2.0":
        raise ValueError("Unsupported emotion state schema")
    return {
        emotion: bool(state.get("triggered"))
        for emotion, state in payload.get("emotions", {}).items()
    }


def HandleEmotionSignalMessage(message) -> tuple[str, int]:
    """解析 V2 普通情绪上升沿或 Calm 持续事件。"""
    payload = json.loads(message.data)
    if payload.get("schema_version") != "2.0":
        raise ValueError("Unsupported emotion signal schema")
    return str(payload["emotion"]), int(payload["value"])
```

推荐处理方式：

- `/emotion/state`：维护当前情绪状态和恢复状态。
- `/emotion/signal_event`：普通情绪可触发一次性行为；Calm 应按持续状态或心跳
  处理，不能每秒重复创建不可重入动作。
- `dominantEmotion`：只用于当前表现选择，不用于判断是否出现新事件。

## 6. 可复现联调步骤

### 6.1 构建并加载当前版本

```bash
cd /home/bird/Marsdog
colcon build --packages-select marsdog_need_emotion
source install/setup.bash
```

每个新终端都需要重新执行：

```bash
cd /home/bird/Marsdog
source install/setup.bash
```

### 6.2 启动节点

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=1 \
  virtual_start_time:=06:00 \
  random_seed:=12345
```

### 6.3 观察状态和事件

终端A：

```bash
ros2 topic echo /emotion/state --field data --full-length
```

终端B：

```bash
ros2 topic echo /emotion/signal_event --field data --full-length
```

### 6.4 注入愉悦事件

终端C：

```bash
ros2 topic pub --once /perception/audio_event std_msgs/msg/String \
  "{data: '{\"event_type\":\"EVT_VOICE_PRAISE\"}'}"
```

默认性格下 `Joy` 从0增加到30，应收到：

```text
EMO_JOY_TRIGGERED
```

`Joy` 会按真实时间衰减。降到30以下时不会收到恢复事件，但
`/emotion/state.emotions.Joy.triggered` 会变为 `false`。

### 6.5 不依赖 ROS2 的确定性验证

```bash
cd /home/bird/Marsdog
python3 - <<'PY'
from marsdog_core import MarsdogEmotionSystem

system = MarsdogEmotionSystem()
system.SetEmotionValue("Joy", 30)
print(system.GetEmotionSignalEventsValue())

system.SetEmotionValue("Joy", 100)
print(system.GetEmotionSignalEventsValue())  # 已触发后升高，无事件

system.SetEmotionValue("Joy", 29)
print(system.GetEmotionSignalEventsValue())  # 下降后恢复 Calm 兜底事件
print(system.GetEmotionSignalEventsValue())  # 平静期间继续输出 Calm

system.SetEmotionValue("Joy", 30)
print(system.GetEmotionSignalEventsValue())  # 再次进入，重新触发
PY
```

预期五次输出依次为：Joy 触发事件、空列表、Calm 事件、Calm 事件、Joy 触发
事件。

## 7. 常见问题与解决方法

### 收不到旧的 `EMO_*_LOW/HIGH` 事件

原因：旧事件已经删除。

解决：改为监听 `EMO_<EMOTION>_TRIGGERED`，同时要求
`schema_version == "2.0"`。

### 等不到情绪恢复事件

原因：V2 不发布 `RECOVERED`。

解决：订阅 `/emotion/state`，读取对应情绪的 `triggered=false`。

### Calm 每秒都会收到

原因：Calm 是无其他触发情绪时的兜底心跳，按真实时间 1 Hz 持续发布，不再是
一次性上升沿。

解决：把 `EMO_CALM_TRIGGERED` 作为“当前保持平静”的持续信号。行为模块需要
自行做动作幂等或状态保持，不要每秒重新启动同一个平静动作。任一其他情绪达到
阈值后，Calm 事件会停止。

### 修改代码后仍看到 V1 字段

原因：当前终端可能仍加载旧的 `install` 目录。

解决：重新执行 `colcon build`，然后在所有联调终端重新
`source install/setup.bash` 并重启节点。

### 收到其他情绪事件但没有重复收到 Joy

原因：一次感知输入可能同时修改多个情绪；每种情绪分别维护触发状态。Joy 已经
触发时不会重复发送，但 Excite 等情绪可能在同一次输入中首次达到自己的阈值。

解决：始终按消息中的 `emotion` 和 `event_type` 分别处理，不要假定每次输入只
产生一种情绪事件。

## 8. 联调验收清单

- [ ] 订阅端只接受情绪 `schema_version=2.0`。
- [ ] 不再读取任何 `level/range/levelEvents/dominantEmotionSignal` 字段。
- [ ] `triggered[]` 使用 `emotion`，不再使用 `type`。
- [ ] 所有旧 `EMO_*_LOW/MID/HIGH/NORMAL` 分支已经删除。
- [ ] 新行为只监听 `EMO_<EMOTION>_TRIGGERED`。
- [ ] 普通情绪按上升沿处理，Calm 按真实时间 1 Hz 的持续心跳处理。
- [ ] 情绪恢复通过 `/emotion/state` 判断，不等待恢复事件。
- [ ] 主导情绪变化不会被当作新触发。
- [ ] 已验证无其他触发情绪时持续收到 Calm，其他情绪触发时停止，回落后恢复。

## 9. 可积累经验

- 状态 Topic 表达“现在是什么”，信号 Topic 表达“刚刚发生了什么”，两者不要
  使用同一套去重逻辑。
- 单一阈值协议下，普通情绪上升沿适合驱动一次性行为；Calm 持续心跳必须使用
  幂等或状态保持逻辑，避免重复启动动作。
- 破坏性字段修改应同步升级 `schema_version`，订阅端应显式校验版本，避免静默
  误读。
- 联调时应同时观察 state 和 signal：只观察 signal 无法判断当前是否已经恢复，
  只观察 state 又无法区分持续状态和新发生的触发。
