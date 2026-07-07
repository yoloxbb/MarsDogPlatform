# MarsDog ROS2 行为树 — 接口文档

## 节点拓扑

```
上游节点（独立运行）                 本项目的节点                   下游
══════════════════                  ════════════                  ════

perception_bridge ─── /audio_event ───→┐
                       /visual_event ──→│
                                        │
emotion_engine_node ── /emotion/state ──→ behavior_tree_node
                      /emotion/signal ──→    │
                                        │    │  /execute_behavior
internal_need_node ─── /need/state ────→│    │  Action Goal/Feedback/Result
                      /need/signal ────→│    │
                                        │    │
                          ┌─────────────┘    ├──────────────→ action_executor_node
                          │                  │
                          │  /perception/    │
                          ├── perception_task│
                          │  (check_person,  │
                          │   detect_objects)│
                          │                  │
                          │  /behavior/result_event
                          └──────────────────→ emotion_engine_node
                                               internal_need_node
```

## 1. 节点

| 节点 | 可执行文件 | 职责 |
|------|-----------|------|
| `/behavior_tree_node` | `behavior_tree_node` | 订阅 5 个上游 topic → 候选池 → BT tick → 仲裁 → Action Client |
| `/action_executor_node` | `action_executor_node` | `/execute_behavior` Action Server（mock，逐步推进动作序列） |

### 启动

```bash
# 全部启动（含 mock 执行器）
ros2 launch marsdog_ros2 behavior_tree.launch.py

# 仅 BT 节点
ros2 launch marsdog_ros2 behavior_tree.launch.py use_mock_executor:=false

# 无 ROS2 开发调试
uv run python -m marsdog_ros2.standalone_demo
```

---

## 2. 订阅的 Topic（5 个输入）

### 2.1 `/emotion/state`

| 属性 | 值 |
|------|-----|
| 发布者 | `emotion_engine_node` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | BEST_EFFORT, KEEP_LAST, depth=5 |
| 频率 | 1Hz |

**作用**：更新 EmotionModule 当前值 + `levelEvents`，供 BehaviorRelevanceCondition 做**字符串比对**。

```json
{
  "emotions": {
    "Joy": 85, "Excite": 40, "Anxiety": 10,
    "Fear": 5, "Curious": 30, "Calm": 60
  },
  "dominant_emotion": "Joy",
  "levelEvents": {
    "Joy": "EMO_JOY_HIGH",
    "Excite": null,
    "Anxiety": null,
    "Fear": null,
    "Curious": null,
    "Calm": "EMO_CALM_NORMAL"
  },
  "personality": {}
}
```

### 2.2 `/emotion/signal_event`

| 属性 | 值 |
|------|-----|
| 发布者 | `emotion_engine_node` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | RELIABLE, KEEP_LAST, depth=10 |
| 频率 | 事件驱动 |

**作用**：收到区间变化事件 → 生成情绪行为候选入池，`trigger_event` 存入 params。

```json
{
  "event_type": "EMO_JOY_HIGH",
  "emotion": "Joy",
  "zone": "HIGH",
  "value": 87
}
```

### 2.3 `/internal_need/state`

| 属性 | 值 |
|------|-----|
| 发布者 | `internal_need_node` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | BEST_EFFORT, KEEP_LAST, depth=5 |
| 频率 | 1Hz |

**作用**：更新 NeedModule 当前值 + `levelEvents`。

```json
{
  "demands": {
    "Hunger": {
      "value": 71, "level": "TRIGGERED",
      "triggerThreshold": 70, "overflowThreshold": 90,
      "triggered": true, "overflow": false
    },
    "Bladder": {"value": 50, "level": "NORMAL", "..."},
    "Sleepiness": {"value": 30, "level": "NORMAL", "..."}
  },
  "levelEvents": {
    "Hunger": "NEED_HUNGER_TRIGGERED",
    "Bladder": "NEED_BLADDER_RECOVERED"
  },
  "triggered": [
    {"type": "Hunger", "value": 71, "triggerThreshold": 70}
  ]
}
```

### 2.4 `/internal_need/signal_event`

| 属性 | 值 |
|------|-----|
| 发布者 | `internal_need_node` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | RELIABLE, KEEP_LAST, depth=10 |
| 频率 | 事件驱动 |

**作用**：收到等级变化事件 → 生成需求行为候选入池。

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

### 2.5 `/perception/audio_event`

| 属性 | 值 |
|------|-----|
| 发布者 | `perception_bridge` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | RELIABLE, KEEP_LAST, depth=10 |
| 频率 | 事件驱动 |

**作用**：过滤 `EVT_VOICE_COMMAND_KNOWN` → `command_id` → `COMMAND_BEHAVIOR_MAP` → 语音行为候选入池。

```json
{
  "event_type": "EVT_VOICE_COMMAND_KNOWN",
  "command_id": "CMD_SIT",
  "intent_category": "command",
  "intent_confidence": 0.95,
  "is_executable": true,
  "asr_text": "坐下",
  "state": "execution"
}
```

---

## 3. 发布的 Topic（1 个输出）

### 3.1 `/behavior/result_event`

| 属性 | 值 |
|------|-----|
| 发布者 | `behavior_tree_node` |
| 类型 | `std_msgs/String` (JSON) |
| QoS | RELIABLE, KEEP_LAST, depth=10 |
| 频率 | 行为完成时 |

**订阅者**：`emotion_engine_node`、`internal_need_node`

```json
{
  "behavior_id": "sig_a1b2c3d4e5f6",
  "behavior_name": "playBow",
  "status": "SUCCESS",
  "result": "COMPLETED",
  "source_event": "EMO_JOY_HIGH",
  "reason": "All action steps finished",
  "reward": 1.0,
  "emotion_delta_json": "{}",
  "need_delta_json": "{}",
  "timestamp": 1783319785.58
}
```

| 字段 | 说明 |
|------|------|
| `behavior_id` | 行为唯一标识 |
| `behavior_name` | 行为名 |
| `status` | BT 原始状态：`SUCCESS` / `FAILURE` / `TIMEOUT` / `CANCELED` |
| `result` | **result_type 映射**：`COMPLETED` / `FAILED` / `TIMEOUT` / `INTERRUPTED` |
| `source_event` | 驱动事件：`"EMO_JOY_HIGH"` / `"NEED_HUNGER_TRIGGERED"` / `"CMD_SIT"` / `""` |
| `reason` | 完成原因描述 |
| `reward` | SUCCESS=1.0, CANCELED=-0.1 |
| `emotion_delta_json` | 情绪增量 JSON（预留） |
| `need_delta_json` | 需求增量 JSON（预留） |
| `timestamp` | Unix 时间戳 |

**`result` 映射（上游节点消费的关键字段）**：

```
status     →  result       →  上游映射           →  情绪变化
SUCCESS    →  COMPLETED    →  DemandSatisfied   →  Joy↑ Calm↑ Anxiety↓
FAILURE    →  FAILED       →  DemandUnsatisfied →  Anxiety↑
TIMEOUT    →  TIMEOUT      →  DemandUnsatisfied →  Anxiety↑
CANCELED   →  INTERRUPTED  →  ActionInterrupted →  Anxiety↑
```

---

## 4. 调用的 Service

### 4.1 `/perception/perception_task`

| 属性 | 值 |
|------|-----|
| 服务端 | `perception_bridge` |
| 类型 | `marsdog_perception/srv/PerceptionTask` |

**调用时机**：

| 场景 | task_type | 作用 |
|------|-----------|------|
| 情绪行为执行前 | `check_person` | 有人 → interactive，无人 → solo |
| 探索行为 | `detect_objects` | 获取可见物体列表 |

```
Request:  {task_id, task_type: "check_person", params_json: "[]"}
Response: {success: true,
           result_json: '[{"key":"present","value":"true"},{"key":"count","value":"1"}]'}
```

---

## 5. Action

### 5.1 `/execute_behavior`

| 属性 | 值 |
|------|-----|
| 类型 | `marsdog_ros2/action/ExecuteBehavior` |
| Client | `behavior_tree_node` |
| Server | `action_executor_node` |

**Goal**：
```json
{
  "goal_id": "goal_abc123",
  "behavior_name": "playBow",
  "priority_level": 5,
  "params_json": "{\"interactive\":true,\"target_identity\":\"owner\"}",
  "timeout_sec": 8.0
}
```

**Feedback**（10Hz，执行中持续推送）：
```json
{
  "goal_id": "goal_abc123",
  "behavior_name": "playBow",
  "status": "RUNNING",
  "progress": 0.5,
  "safe_to_interrupt": true,
  "current_action": "ACT_PLAY_BOW_INVITE",
  "message": "Step 1/1: ACT_PLAY_BOW_INVITE"
}
```

**Result**（行为完成/取消时）：
```json
{
  "goal_id": "goal_abc123",
  "behavior_name": "playBow",
  "status": "SUCCESS",
  "result": "completed",
  "reason": "All action steps finished",
  "reward": 1.0,
  "emotion_delta_json": "{}",
  "need_delta_json": "{}"
}
```

---

## 6. 核心逻辑：状态比对

行为树**不做值判断**，只比对上游发布的事件字符串。

### 情绪

```
1. /emotion/signal_event: event_type="EMO_JOY_HIGH"
   → 候选入池 params={trigger_event: "EMO_JOY_HIGH", source_emotion: "Joy"}

2. /emotion/state: levelEvents["Joy"]="EMO_JOY_HIGH"  (每 1 秒更新)

3. BT 轮到 Lv5 执行时 → BehaviorRelevanceCondition:
   current_event = levelEvents["Joy"]      → "EMO_JOY_HIGH"
   trigger_event = params.trigger_event    → "EMO_JOY_HIGH"
   比对: "EMO_JOY_HIGH" == "EMO_JOY_HIGH" → SUCCESS → 执行

4. 情绪衰减后:
   levelEvents["Joy"] = "EMO_JOY_MID"
   比对: "EMO_JOY_MID" != "EMO_JOY_HIGH"  → FAILURE → SKIP
```

### 需求（同理）

```
levelEvents["Hunger"] == "NEED_HUNGER_TRIGGERED"
    vs trigger_event == "NEED_HUNGER_TRIGGERED"    → 执行
levelEvents["Hunger"] == "NEED_HUNGER_RECOVERED"
    vs trigger_event == "NEED_HUNGER_TRIGGERED"    → SKIP
```

---

## 7. 调试

```bash
# 查看上游 topic
ros2 topic echo /emotion/state --once
ros2 topic echo /internal_need/state --once
ros2 topic echo /perception/audio_event

# 查看 BT 发布的反馈
ros2 topic echo /behavior/result_event

# 手动发 goal 测试执行器
ros2 action send_goal /execute_behavior marsdog_ros2/action/ExecuteBehavior \
  "{behavior_name: 'playBow', priority_level: 5, timeout_sec: 8.0}" --feedback

# 手动调用感知服务
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 'test', task_type: 'check_person', params_json: '[]'}"
```
