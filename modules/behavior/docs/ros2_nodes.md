# MarsDog ROS2 节点说明文档

## 节点总览

| 节点名 | 包 | 可执行文件 | 说明 |
|--------|-----|-----------|------|
| `/behavior_tree_node` | `marsdog_behavior` | `behavior_tree_node` | 行为树决策引擎（本项目） |
| `/action_executor_node` | `marsdog_action_executor` | `action_executor_node` | 动作执行器（独立项目） |

> `marsdog_action_executor` 不在本仓库，这里只列出其接口关系。

---

## 一、`/behavior_tree_node`

### 启动方式

```bash
# 方式 1：launch 文件
ros2 launch marsdog_behavior behavior_tree.launch.py

# 方式 2：直接运行
ros2 run marsdog_behavior behavior_tree_node

# 方式 3：无 ROS2 环境（开发调试）
uv run python -m marsdog_behavior.standalone_demo
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tick_rate` | float | 0.1 | BT 评估频率（秒），默认 10Hz |

### 订阅

| Topic | 类型 | QoS | 说明 |
|-------|------|-----|------|
| `/emotion/state` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 6 种情绪当前值 + levelEvents，1Hz |
| `/emotion/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 情绪区间变化事件，事件驱动 |
| `/internal_need/state` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 7 种需求当前值 + levelEvents，1Hz |
| `/internal_need/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 需求等级变化事件，事件驱动 |
| `/perception/audio_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 声音事件（仅白名单事件生成候选） |
| `/perception/visual_event` | `std_msgs/String` (JSON) | BEST_EFFORT, depth=5 | 视觉事件（仅用于 active_target 缓存） |

### 发布

| Topic | 类型 | QoS | 说明 |
|-------|------|-----|------|
| `/behavior/result_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 需求行为结果（STARTED/COMPLETED/FAILED/TIMEOUT/INTERRUPTED） |

### Action Client

| Action | 方向 | 说明 |
|--------|------|------|
| `/execute_behavior` | Client → Server | 下发 `behavior_name` 到 `marsdog_action_executor` |

### Service Client（预留）

| Service | 说明 |
|---------|------|
| `/perception/perception_task` | `check_person` / `detect_objects`（当前用 visual_event 缓存替代） |

---

## 二、`/action_executor_node`（参考，非本项目）

### 启动方式

```bash
ros2 run marsdog_action_executor action_executor_node
```

### Action Server

| Action | 方向 | 说明 |
|--------|------|------|
| `/execute_behavior` | ← Client | 接收 `behavior_name`，执行动作序列 |

### 发布的调试 Topic

| Topic | 类型 | 频率 | 说明 |
|-------|------|------|------|
| `/execute_behavior/goal` | `std_msgs/String` (JSON) | 事件驱动 | goal 下发时 |
| `/execute_behavior/feedback` | `std_msgs/String` (JSON) | 10Hz | 进度 + 当前动作 |
| `/execute_behavior/result` | `std_msgs/String` (JSON) | 事件驱动 | 完成/取消/超时时 |

> 这三个是调试接口，不作为行为树项目的正式依赖。

---

## 三、Launch 文件

`launch/behavior_tree.launch.py`：

```python
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    tick_rate = LaunchConfiguration("tick_rate", default="0.1")
    return LaunchDescription([
        DeclareLaunchArgument("tick_rate", default_value="0.1",
            description="BT tick rate in seconds (10Hz default)"),
        Node(
            package="marsdog_behavior",
            executable="behavior_tree_node",
            name="behavior_tree_node",
            output="screen",
            parameters=[{"tick_rate": tick_rate}],
        ),
    ])
```

### 启动参数

```bash
# 修改 tick 频率为 5Hz
ros2 launch marsdog_behavior behavior_tree.launch.py tick_rate:=0.2

# 不启动 action_executor（单独启动）
ros2 launch marsdog_behavior behavior_tree.launch.py
ros2 run marsdog_action_executor action_executor_node
```

---

## 四、消息格式

### 4.1 `/emotion/state`

```json
{
  "emotions": {
    "Joy": {"value": 72, "level": "MID", "levelEvent": "EMO_JOY_MID", "triggered": true},
    "Excite": {"value": 10, "level": "NONE", "levelEvent": null, "triggered": false},
    "Anxiety": {"value": 5, "level": "NONE", "levelEvent": null, "triggered": false},
    "Fear": {"value": 3, "level": "NONE", "levelEvent": null, "triggered": false},
    "Curious": {"value": 15, "level": "NONE", "levelEvent": null, "triggered": false},
    "Calm": {"value": 50, "level": "NORMAL", "levelEvent": "EMO_CALM_NORMAL", "triggered": true}
  },
  "levelEvents": {
    "Joy": "EMO_JOY_MID",
    "Excite": null,
    "Anxiety": null,
    "Fear": null,
    "Curious": null,
    "Calm": "EMO_CALM_NORMAL"
  },
  "dominantEmotion": "Joy"
}
```

### 4.2 `/emotion/signal_event`

```json
{
  "event_type": "EMO_JOY_MID",
  "emotion": "Joy",
  "value": 72,
  "level": "MID",
  "range": [61, 85],
  "trigger": "LEVEL_CHANGED",
  "isDominant": true
}
```

### 4.3 `/internal_need/state`

```json
{
  "demands": {
    "Hunger": {"value": 71, "level": "TRIGGERED", "levelEvent": "NEED_HUNGER_TRIGGERED", "triggered": true},
    "Bladder": {"value": 50, "level": "NORMAL", "levelEvent": "NEED_BLADDER_RECOVERED", "triggered": false},
    "Sleepiness": {"value": 30, "level": "NORMAL", "levelEvent": "NEED_SLEEPINESS_RECOVERED", "triggered": false},
    "Cleanliness": {"value": 40, "level": "NORMAL", "levelEvent": "NEED_CLEANLINESS_RECOVERED", "triggered": false},
    "Energy": {"value": 85, "level": "NORMAL", "levelEvent": "NEED_ENERGY_RECOVERED", "triggered": false},
    "Social": {"value": 40, "level": "NORMAL", "levelEvent": "NEED_SOCIAL_RECOVERED", "triggered": false},
    "Exploration": {"value": 30, "level": "NORMAL", "levelEvent": "NEED_EXPLORATION_RECOVERED", "triggered": false}
  },
  "levelEvents": {
    "Hunger": "NEED_HUNGER_TRIGGERED",
    "Bladder": "NEED_BLADDER_RECOVERED",
    "Sleepiness": "NEED_SLEEPINESS_RECOVERED",
    "Cleanliness": "NEED_CLEANLINESS_RECOVERED",
    "Energy": "NEED_ENERGY_RECOVERED",
    "Social": "NEED_SOCIAL_RECOVERED",
    "Exploration": "NEED_EXPLORATION_RECOVERED"
  }
}
```

### 4.4 `/internal_need/signal_event`

```json
{
  "event_type": "NEED_HUNGER_TRIGGERED",
  "demand": "Hunger",
  "value": 71,
  "level": "TRIGGERED",
  "previousLevel": "NORMAL",
  "trigger": "LEVEL_CHANGED"
}
```

### 4.5 `/perception/audio_event`

```json
{
  "event_type": "EVT_VOICE_COMMAND_KNOWN",
  "command_id": "CMD_SIT",
  "intent_confidence": 0.95,
  "is_executable": true,
  "asr_text": "坐下"
}
```

行为树白名单：`EVT_VOICE_CALL_NAME`、`EVT_VOICE_COMMAND_KNOWN`。

### 4.6 `/perception/visual_event`

```json
{
  "active_target": {"track_id": 1, "identity": "owner"},
  "events": ["EVT_VISION_MASTER"]
}
```

行为树只用 `active_target` 缓存，`events` 数组不生成行为候选。

### 4.7 `/behavior/result_event`

```json
{
  "event_id": "result-000042",
  "timestamp": 1783408067.68,
  "action_type": "ACTION_EAT",
  "demand_type": "Hunger",
  "result_type": "COMPLETED",
  "metadata": {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"}
}
```

### 4.8 `/execute_behavior` Goal（Action Client 下发）

```json
{
  "behavior_name": "expressJoy",
  "priority_level": 5,
  "params_json": "{\"source\":\"emotion\",\"trigger_event\":\"EMO_JOY_MID\",\"level\":\"MID\",\"variant\":\"joy_mid\",\"interaction_mode\":\"solo\",\"result_mapping\":null}",
  "timeout_sec": 8.0
}
```

---

## 五、调试命令

```bash
# 查看情绪状态
ros2 topic echo /emotion/state --once

# 查看信号事件
ros2 topic echo /emotion/signal_event

# 查看需求状态
ros2 topic echo /internal_need/state --once

# 查看行为结果
ros2 topic echo /behavior/result_event

# 手动发声音指令（触发 CMD_SIT）
ros2 topic pub --once /perception/audio_event std_msgs/msg/String \
  "{data: '{\"event_type\":\"EVT_VOICE_COMMAND_KNOWN\",\"command_id\":\"CMD_SIT\",\"is_executable\":true,\"intent_confidence\":0.95}'}"

# 手动发视觉事件
ros2 topic pub --once /perception/visual_event std_msgs/msg/String \
  "{data: '{\"events\":[\"EVT_VISION_TOY\"],\"active_target\":{\"identity\":\"owner\"}}'}"

# 手动发情绪 signal_event
ros2 topic pub --once /emotion/signal_event std_msgs/msg/String \
  "{data: '{\"event_type\":\"EMO_JOY_HIGH\",\"emotion\":\"Joy\",\"value\":90,\"level\":\"HIGH\",\"trigger\":\"LEVEL_CHANGED\"}'}"

# 手动发需求 signal_event
ros2 topic pub --once /internal_need/signal_event std_msgs/msg/String \
  "{data: '{\"event_type\":\"NEED_HUNGER_TRIGGERED\",\"demand\":\"Hunger\",\"value\":75,\"level\":\"TRIGGERED\"}'}"
```

---

## 六、节点拓扑

```
┌──────────────────────────────────────────────────────────────────┐
│ 上游节点（独立项目）                                               │
│                                                                  │
│  emotion_engine_node    → /emotion/state (1Hz)                    │
│                         → /emotion/signal_event (event)           │
│  internal_need_node     → /internal_need/state (1Hz)              │
│                         → /internal_need/signal_event (event)     │
│  perception_bridge      → /perception/audio_event (event)         │
│                         → /perception/visual_event (event)        │
│                         ← /perception/perception_task (service)    │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│ /behavior_tree_node（本项目）                                      │
│                                                                  │
│  订阅 6 个 topic → IntentMapper → CandidatePool → BT tick (10Hz) │
│  Action Client → /execute_behavior                                │
│  发布 → /behavior/result_event                                    │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│ /action_executor_node（独立项目 marsdog_action_executor）          │
│                                                                  │
│  Action Server: /execute_behavior                                 │
│  Goal → 动作序列 → Feedback (progress) → Result                   │
│  调试 Topic: /execute_behavior/goal|feedback|result               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 七、相关文档

| 文档 | 内容 |
|------|------|
| [visualization_interface.md](visualization_interface.md) | Topic JSON Schema 完整定义、状态机、可视化布局 |
| [event_intent_pipeline.md](event_intent_pipeline.md) | 事件→Intent→Behavior 管道、白名单、链路示例 |
| [behavior_tree_internals.md](behavior_tree_internals.md) | 行为树内部逻辑：7层仲裁、抢占、相关性 |
| [behavior_semantic_map.md](behavior_semantic_map.md) | 需求/情绪→行为完整映射表 |
