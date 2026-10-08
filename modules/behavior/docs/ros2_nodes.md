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
| `/emotion/state` | `std_msgs/String` (JSON) | BEST_EFFORT, depth=5 | V2：6 种情绪当前值 + triggered，1Hz |
| `/emotion/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | V2：单阈值上升沿事件 |
| `/internal_need/state` | `std_msgs/String` (JSON) | BEST_EFFORT, depth=5 | V2：7 种需求完整当前状态，1Hz |
| `/internal_need/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | V2：需求等级变化事件 |
| `/perception/audio_event` | `std_msgs/String` (JSON v2) | RELIABLE, depth=10 | 声音事件（仅精确授权白名单生成候选） |
| `/perception/visual_event` | `std_msgs/String` (JSON v1) | BEST_EFFORT, depth=5 | 场景缓存；STRANGER 情绪融合；FALL/STOP 直接候选 |

### 发布

| Topic | 类型 | QoS | 说明 |
|-------|------|-----|------|
| `/behavior/result_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 需求行为结果（STARTED/COMPLETED/FAILED/TIMEOUT/INTERRUPTED） |
| `/behavior/attention_tracking` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 语音会话的人脸居中控制；长期 UWB 跟随由 Action Goal 持有 |

### Action Client

| Action | 方向 | 说明 |
|--------|------|------|
| `/execute_behavior` | Client → Server | 下发 `behavior_name` 到 `marsdog_action_executor` |

### Service Client

| Service | 说明 |
|---------|------|
| `/perception/vision/task` | `marsdog_vision_interaction/srv/VisionTask`；Emotion/Hunger/Social/Exploration 调用 `check_person` / `detect_objects` |
| `/perception/perception_task` | 旧 `PerceptionTask` 接口兼容回退 |

`VisionTask` 的传输字段：

```text
# Request
string task_id
string task_type       # check_person | detect_objects
string params_json     # {} 或 {"confidence": 0.5}
---
# Response
bool success
string task_id
string task_type
string result_json
string error_message
float64 latency_ms
```

新版 `check_person.result_json` 为 `{"ok":true,"present":true,"count":1}`，
`detect_objects.result_json` 为 `{"ok":true,"objects":[...]}`。适配器也会归一化
旧 `PerceptionTask` 的 `[{"key":"...","value":"..."}]` 返回格式。

情绪事件调用 `check_person` 后按以下规则创建候选：

| `event_type` | `present=true` | `present=false` |
|---|---|---|
| `EMO_CALM_TRIGGERED` | `expressCalmWithHuman` | `expressCalmAlone` |
| `EMO_JOY_TRIGGERED` | `expressJoyWithHuman` | `expressJoyAlone` |
| `EMO_EXCITE_TRIGGERED` | `expressExcitementWithHuman` | `expressExcitementAlone` |
| `EMO_ANXIETY_TRIGGERED` | `expressAnxietyWithHuman` | `expressAnxietyAlone` |
| `EMO_FEAR_TRIGGERED` | `expressFearWithHuman` | `expressFearAlone` |
| `EMO_CURIOUS_TRIGGERED` | `expressCuriosityWithHuman` | `expressCuriosityAlone` |

如果等待 Service 期间 `/emotion/state` 已变为 `triggered=false`，迟到结果不会
生成行为候选。视觉 Service 不可用时回退到 `/perception/visual_event` 场景
缓存；Standalone 模式使用虚拟人物场景。

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
| `/debug/execute_behavior/goal` | `std_msgs/String` (JSON) | 事件驱动 | goal 下发时 |
| `/debug/execute_behavior/feedback` | `std_msgs/String` (JSON) | 每个 Stage 后 | 进度 + 当前动作 |
| `/debug/execute_behavior/result` | `std_msgs/String` (JSON) | 事件驱动 | 完成/取消/超时时 |

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
  "schema_version": "2.0",
  "timestamp": 1785290000.0,
  "emotions": {
    "Joy": {"value": 30, "triggerThreshold": 30, "triggerOperator": "gte", "triggered": true},
    "Excite": {"value": 20, "triggerThreshold": 40, "triggerOperator": "gte", "triggered": false},
    "Anxiety": {"value": 10, "triggerThreshold": 25, "triggerOperator": "gte", "triggered": false},
    "Fear": {"value": 10, "triggerThreshold": 30, "triggerOperator": "gte", "triggered": false},
    "Curious": {"value": 10, "triggerThreshold": 20, "triggerOperator": "gte", "triggered": false},
    "Calm": {"value": 30, "triggerThreshold": 0, "triggerOperator": "gte", "triggered": true}
  },
  "triggered": [
    {"emotion": "Joy", "value": 30, "eventType": "EMO_JOY_TRIGGERED", "triggerThreshold": 30, "triggerOperator": "gte"},
    {"emotion": "Calm", "value": 30, "eventType": "EMO_CALM_TRIGGERED", "triggerThreshold": 0, "triggerOperator": "gte"}
  ],
  "dominantEmotion": "Joy"
}
```

行为树只接受 `schema_version="2.0"`。state 是当前权威状态，只更新缓存；
`triggered=false` 用于使尚未执行的情绪候选失效，不产生恢复候选。
`triggered[]` 是当前集合，不是本次新增事件列表。

### 4.2 `/emotion/signal_event`

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

signal 仅表示 `triggered: false → true` 的上升沿。持续升高、恢复和主导情绪
变化都不发布事件。行为树同时校验 `event_type` 与 `emotion`，并将其映射为
一次性 Lv5 情绪行为候选。

### 4.3 `/internal_need/state`

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "demands": {
    "Social": {
      "value": 71,
      "triggerThreshold": 60,
      "triggerOperator": "gt",
      "urgentThreshold": 70,
      "urgentOperator": "gt",
      "overflowThreshold": 85,
      "triggered": true,
      "urgent": true,
      "overflow": false,
      "level": "URGENT",
      "levelEvent": "NEED_SOCIAL_URGENT",
      "levelActive": true
    }
  },
  "timeContext": {}
}
```

行为树只接受 `schema_version="2.0"`，并校验 `value`、阈值、布尔状态、
`level` 和 `levelEvent` 彼此一致。state 是权威状态，不直接生成行为候选；
它会更新相关性，并清除与当前等级不一致的排队候选。

首次触发线必须读取 `triggerThreshold / triggerOperator`。可选中间紧急线
使用 `urgentThreshold / urgentOperator`；未配置时必须为 `null/null`。

### 4.4 `/internal_need/signal_event`

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "event_type": "NEED_SOCIAL_URGENT",
  "demand": "Social",
  "value": 71,
  "level": "URGENT",
  "previousLevel": "TRIGGERED",
  "triggerThreshold": 60,
  "triggerOperator": "gt",
  "urgentThreshold": 70,
  "urgentOperator": "gt",
  "overflowThreshold": 85,
  "overflowOperator": "gt",
  "trigger": "LEVEL_CHANGED",
  "timeContext": {}
}
```

等级变化时发布变化后的当前等级。Social 下降序列为
`OVERFLOW → NEED_SOCIAL_URGENT`、
`URGENT → NEED_SOCIAL_TRIGGERED`、
`TRIGGERED → NEED_SOCIAL_RECOVERED`。RECOVERED 只更新状态和清理旧候选，
不创建行为。

| 需求 | NORMAL | TRIGGERED | URGENT | OVERFLOW |
|------|--------|-----------|--------|----------|
| Hunger | 0-70 | 71-90 | — | 91-100 |
| Bladder | 0-75 | 76-100 | — | — |
| Sleepiness | 0-65 | 66-90 | — | 91-100 |
| Cleanliness | 0-70 | 71-100 | — | — |
| Energy | 0-80 | 81-90 | — | 91-100 |
| Social | 0-60 | 61-70 | 71-85 | 86-100 |
| Exploration | 0-60 | 61-100 | — | — |

所有比较符均为严格 `gt`。Bladder、Cleanliness、Exploration 到 100 仍为
`TRIGGERED`。Energy 是电量缺口（`100 - 实际电量百分比`）；结果 metadata
里的 `energyValue / energy_value / batteryValue` 仍是实际电量，不做反转。

### 4.5 `/perception/audio_event`

```json
{
  "schema_version": 2,
  "event_type": "EVT_VOICE_COMMAND_SIT",
  "interaction_id": "voice-001",
  "utterance_id": "utterance-001",
  "command_id": "CMD_SIT",
  "specific_event_type": "EVT_VOICE_COMMAND_SIT",
  "dispatch_role": "specific_command",
  "should_trigger_behavior_tree": true,
  "intent_confidence": 0.95,
  "asr_text": "请坐下",
  "slots": []
}
```

行为树只接受整数 `schema_version=2`。除硬件唤醒和会话终态外，
已配置的 `EVT_VOICE_COMMAND_<ACTION>` 还必须通过 `command_id`、
`specific_event_type`、`dispatch_role=specific_command` 和
`should_trigger_behavior_tree=true` 校验。

- 只有 `EVT_VOICE_WAKEUP` 创建会话并生成正式 `respond_owner_call` 候选；该行为
  只按 `microphone_array` 下的原始 `wake_angle` 原地转向，执行期间不启动后台
  attention 底盘控制；offset/sign 只由 Action 标定。
- 同一 `interaction_id` 的新 `wake_id` 会替换旧唤醒会话并请求取消旧 Goal；
  调度须等待真实 Result。相同 `wake_id` 的重报只处理一次。Tree 只接收匹配当前
  `interaction_id + wake_id` 的 `EVT_VOICE_WAKE_SPEAKER_RESULT`。
- `EVT_VOICE_CALL_NAME` 和 `EVT_VOICE_COMMAND_CALL_NAME` 是纯社交通知，不创建
  会话或候选，即使权限字段异常为真也不能进入命令回调。
- `EVT_VOICE_COMMAND_PRAISE/SCOLD` 只接受
  `dispatch_role=social_reaction`、`is_executable=false`、
  `should_trigger_behavior_tree=true`。它们消费同一语音轮次，生成
  Lv1 `audio_reaction`；活跃会话的人体分支固定为
  `*InPlaceWithHuman`。
- 转向成功后等待声纹结果最多 3 秒。只有 `owner/family + matched` 会异步调用
  `VisionTask.query_targets`，按声源方向在前方 `±25°` 内绑定稳定人体
  `vision_epoch + target_id` 并生成 `approach_voice_caller`。陌生人、无法判定、
  超时和明确视觉身份冲突均原地进入 WAITING，关闭 attention 底盘转向。
- Action 对锁定人体请求一次 `VisionTask.locate_person_once`。Vision 当前只返回
  视觉候选；Action 将其作为 `visual_target_only_no_navigation_geometry` 失败处理，
  不发送 `/navigate_to_pose`，也没有 bbox 速度回退。
- `query_targets` 超过 2 秒会作废该 generation；迟到结果不能重新触发移动。
- 行为树用 `VoiceTask.hold_interaction` 的有限租约覆盖转向、声纹等待、视觉查询和靠近耗时，
  到达后 `release_interaction_hold(reset_idle_timer=true)`。
- 强指令只按审核后的完整 `event_type + command_id` 映射为专用 Behavior。
- `unhappy`、`miss_owner`、`farewell_leave` 在入候选池前异步执行
  `query_targets`，只接受带 `vision_epoch + target_id + identity=owner` 的当前
  主人目标并写入 `params_json.target`。无人、陌生人或不稳定目标时不下发移动
  Goal；新语音指令会使迟到的视觉回调失效。三者 Goal 超时统一为 25 秒，以覆盖
  Action 最长 20 秒的视觉接近及后续表达阶段。
- `approach_owner`、`come_to_owner`、`return_to_owner` 直接入候选池，不调用
  `query_targets`。Action 从新鲜的视觉事件绑定当前人体轨迹，视觉身份可以为
  `unknown`，再调用一次视觉版 `locate_person_once`；无人或目标失鲜则失败停车，
  当前任务没有地图几何，因此不会启动 Nav2 接近。
- TOILET/CLEAN/SLEEP 分别要求最新内部状态严格满足 `Bladder > 50`、
  `Cleanliness > 40`、`Sleepiness > 50`，之后复用
  `barkShortAlert/lickPaws/sleepOnSide`；缺状态和等于阈值都不执行。
- 19 个 `core: true` 产品指令全部开放；WALK、GO_OUT、GO_HOME、APPROACH、
  BACK_UP、STAND_STILL、HOLD_POSITION、QUIET 分别映射为
  `walk_to_random_point`、`go_out_to_play`、`go_home`、`approach_owner`、
  `back_up`、`stand_still`、`hold_position`、`quiet`。
- KNOWN 摘要、语义分类、诊断事件和 `speech` 不生成候选。
- Model Intent FETCH 还要求 `slots.object_name` 非 `NONE`，目标证据保留到 Goal 参数。
- `EVT_VOICE_COMMAND_DROP` 输出 Lv1 `drop_object`；
  `EVT_VOICE_COMMAND_STOP` 输出 Lv0 `emergency_stop`。

### 4.6 `/perception/visual_event`

```json
{
  "schema_version": 1,
  "header": {"stamp": 1786417000.1, "frame_id": "camera_link"},
  "active_target": {"track_id": 7, "pose_action": "fallen_down"},
  "hands": [{"hand_action": "stop_gesture"}],
  "events": ["EVT_VISION_FALL", "EVT_VISION_STOP_GESTURE"]
}
```

行为树缓存 `humans`、`active_target` 和 `tracked_objects`，供视觉服务不可用时
回退。`events[]` 只接受字符串，直接行为白名单为：

| event | Behavior | priority | TTL |
|---|---|---|---|
| `EVT_VISION_FALL` | `respond_person_fall` | Lv1, `sub_priority=12` | 8s |
| `EVT_VISION_STOP_GESTURE` | `respond_stop_gesture` | Lv1, `sub_priority=12` | 8s |

该 Topic 是 10 Hz 状态快照。同一事件连续出现时只生成一次候选；事件先从
`events[]` 消失、之后再出现才会重新触发。其余 `EVT_VISION_*` 仍只作为
场景/情绪上下文，不直接生成候选。

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

充电行为 `recharge` / `restInPlace` 成功后固定发布内部需求可结算的规范字段：

```json
{
  "action_type": "ACTION_RECHARGE",
  "demand_type": "Energy",
  "result_type": "COMPLETED",
  "metadata": {"energyValue": 88, "recoveryMode": "charging"}
}
```

`energyValue` 是实际电量百分比，缺失或非法时按契约补为 `100`，并限制在
`0..100`。终态发布后行为树会清空 `current_behavior/current_goal_id`；同一 tick
内刚启动的抢占替代行为不会被误清理。

### 4.8 `/execute_behavior` Goal（Action Client 下发）

```json
{
  "behavior_name": "expressJoy",
  "priority_level": 5,
  "params_json": "{\"source\":\"emotion\",\"trigger_event\":\"EMO_JOY_TRIGGERED\",\"variant\":\"joy\",\"interaction_mode\":\"solo\",\"executor_behavior_name\":\"expressJoy\",\"result_mapping\":null}",
  "timeout_sec": 8.0
}
```

情绪候选在行为树内使用 `expressJoyWithHuman` / `expressJoyAlone`。Action
Client 通过 `executor_behavior_name` 向现有执行器发送基础模板
`expressJoy`，反馈回到行为树时恢复为原始的分支 Behavior 名。

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

# 手动发声音事件（触发 sit_down）
ros2 topic pub --once /perception/audio_event std_msgs/msg/String \
  "{data: '{\"schema_version\":2,\"event_type\":\"EVT_VOICE_COMMAND_SIT\",\"interaction_id\":\"manual-1\",\"utterance_id\":\"manual-u1\",\"command_id\":\"CMD_SIT\",\"specific_event_type\":\"EVT_VOICE_COMMAND_SIT\",\"dispatch_role\":\"specific_command\",\"should_trigger_behavior_tree\":true,\"intent_confidence\":0.95,\"slots\":[]}'}"

# 手动发视觉跌倒事件（触发 respond_person_fall）
ros2 topic pub --once /perception/visual_event std_msgs/msg/String \
  "{data: '{\"schema_version\":1,\"header\":{\"stamp\":1786417000.1,\"frame_id\":\"camera_link\"},\"active_target\":{\"track_id\":7,\"pose_action\":\"fallen_down\"},\"faces\":[],\"humans\":[],\"hands\":[],\"tracked_objects\":[],\"events\":[\"EVT_VISION_FALL\"]}'}"

# 手动发情绪 signal_event
ros2 topic pub --once /emotion/signal_event std_msgs/msg/String \
  "{data: '{\"schema_version\":\"2.0\",\"event_type\":\"EMO_JOY_TRIGGERED\",\"emotion\":\"Joy\",\"value\":30,\"triggerThreshold\":30,\"triggerOperator\":\"gte\"}'}"

# 手动发需求 signal_event
ros2 topic pub --once /internal_need/signal_event std_msgs/msg/String \
  "{data: '{\"schema_version\":\"2.0\",\"event_type\":\"NEED_SOCIAL_URGENT\",\"demand\":\"Social\",\"value\":71,\"level\":\"URGENT\",\"previousLevel\":\"TRIGGERED\",\"triggerThreshold\":60,\"triggerOperator\":\"gt\",\"urgentThreshold\":70,\"urgentOperator\":\"gt\",\"overflowThreshold\":85,\"overflowOperator\":\"gt\",\"trigger\":\"LEVEL_CHANGED\"}'}"
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
│                         ← /perception/vision/task (service)        │
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
| [HANDOFF.md](HANDOFF.md) | 项目边界、上下游契约、队列、跟随和充电流程 |
| [event_behavior_table.md](event_behavior_table.md) | 语音/需求/情绪事件到 Behavior 的完整映射 |
| [behavior_tree_architecture.md](behavior_tree_architecture.md) | 行为树内部逻辑：7层仲裁、抢占、相关性 |
| [architecture.md](architecture.md) | 整体模块架构 |
# 会话注视控制

行为树只在唤醒转向/靠近结束后的 WAITING 阶段发布
`/behavior/attention_tracking`（`std_msgs/String` JSON）。动作系统据此启动或停止
锁定人体的居中控制；该通道不等同于 `CMD_FOLLOW`，也不会与正式 Action Goal
同时控制底盘。
