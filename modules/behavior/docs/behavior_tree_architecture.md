# 行为树架构与上下游关联文档

本文档完整描述 MarsDog 行为树系统的架构、上下游接口、数据流和内部机制。所有内容以当前代码为准。

---

## 1. 系统总览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              上游节点（独立项目）                                │
│                                                                              │
│  emotion_engine_node     → /emotion/state (1Hz, BEST_EFFORT)                  │
│                          → /emotion/signal_event (EVENT, RELIABLE)            │
│  internal_need_node      → /internal_need/state (1Hz, BEST_EFFORT)            │
│                          → /internal_need/signal_event (EVENT, RELIABLE)      │
│  perception_bridge       → /perception/audio_event (EVENT, RELIABLE)          │
│                          → /perception/visual_event (EVENT, BEST_EFFORT)      │
│                          ← /perception/vision/task (SERVICE)                  │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                     marsdog_behavior (/behavior_tree_node)                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ BehaviorTreeRosNode (ros_node.py)                                    │     │
│  │   - 6 个 ROS2 Subscription 回调                                       │     │
│  │   - 1 个 Action Client: /execute_behavior                            │     │
│  │   - 1 个 Publisher: /behavior/result_event                           │     │
│  │   - 1 个 Timer: 100ms tick                                           │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ IntentMapper (intent_mapper.py)                                      │     │
│  │   - 事件 → category → intent → BehaviorCandidate                     │     │
│  │   - 去重键: (source, trigger_event, behavior_name, variant, mode)      │     │
│  │   - TTL: 10.0s (默认), cooldown, interrupt_policy                    │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ CandidatePool (candidate_pool.py)                                    │     │
│  │   - 线程安全候选队列 + 复合键去重                                       │     │
│  │   - 排序: level ASC → sub_priority ASC → value DESC → created_at DESC│     │
│  │   - 冷却等待: 不丢弃，冷却结束或 TTL 过期后释放                           │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ BehaviorRuntime (runtime.py)                                         │     │
│  │   - select_best() → ActiveBehavior                                   │     │
│  │   - tree.reset() + tree.tick()                                       │     │
│  │   - 观察 STARTED / 终态事件                                          │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ bionic_dog_bt (纯运行时，无 ROS2 依赖)                                  │     │
│  │                                                                      │     │
│  │  Root Selector (reactive, memory=False)                               │     │
│  │  ├── Lv0_System:               Condition → Relevance → Execute       │     │
│  │  ├── Lv1_ExternalInteraction:  Condition → Relevance → Execute       │     │
│  │  ├── Lv2_PhysioUrgent:         Condition → Relevance → Execute       │     │
│  │  ├── Lv3_PhysioNormal:         Condition → Relevance → Execute       │     │
│  │  ├── Lv4_Psychological:        Condition → Relevance → Execute       │     │
│  │  ├── Lv5_EmotionExpression:    Condition → Relevance → Execute       │     │
│  │  └── Lv6_Idle:                 Condition → Relevance → Execute       │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ ActionClientAdapter / MockActionExecutor                             │     │
│  │   - send_goal(ActiveBehavior) → goal_id                             │     │
│  │   - get_feedback() → ExecutorFeedback                                │     │
│  │   - get_result() → BehaviorFeedbackEvent                             │     │
│  │   - cancel_goal()                                                    │     │
│  └──────────────────────────────┬──────────────────────────────────────┘     │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐     │
│  │ ResultEventMapper (result_event_mapper.py)                           │     │
│  │   - 需求行为 → /behavior/result_event JSON                            │     │
│  │   - Status mapping: SUCCESS→COMPLETED, FAILURE→FAILED,               │     │
│  │     CANCELED→INTERRUPTED, TIMEOUT→TIMEOUT                            │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                         /execute_behavior Action
                         (Goal / Feedback / Result)
                                   │
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                     marsdog_action_executor（独立项目）                         │
│                                                                              │
│  Action Server: /execute_behavior                                            │
│  Goal {behavior_name, priority_level, params_json, timeout_sec}              │
│    → 动作序列编排                                                             │
│    → Feedback {progress, safe_to_interrupt, current_action}                  │
│    → Result {status, reason, reward, emotion_delta, need_delta}              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 上游连接：ROS2 订阅与事件来源

### 2.1 订阅总览

| # | Topic | 类型 | QoS | 用途 | 生成候选 |
|---|-------|------|-----|------|---------|
| 1 | `/emotion/state` | `std_msgs/String` (JSON) | BEST_EFFORT, depth=5 | V2 数值 + triggered，含恢复 | **否** |
| 2 | `/emotion/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | V2 单阈值上升沿 → 情绪行为候选 | **是** |
| 3 | `/internal_need/state` | `std_msgs/String` (JSON) | BEST_EFFORT, depth=5 | V2 完整需求状态 + 相关性 | **否** |
| 4 | `/internal_need/signal_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | V2 等级变化 → 需求行为候选 | **是**（RECOVERED 除外） |
| 5 | `/perception/audio_event` | `std_msgs/String` (JSON) | RELIABLE, depth=10 | 音频指令 → 外部交互候选 | **是**（白名单） |
| 6 | `/perception/visual_event` | `std_msgs/String` (JSON v1) | BEST_EFFORT, depth=5 | 场景缓存 + STRANGER 融合 + FALL/STOP 白名单 | **是**（仅白名单） |

### 2.2 `state` vs `signal_event` 的分工

情绪 V2 中，signal 表示“刚刚越过阈值”，用于创建一次候选；
`state.emotions.<name>.triggered` 表示“现在是否仍达到阈值”，用于相关性校验。
signal 回调会立即将该情绪标记为 triggered，避免等待下一次 1 Hz state；
恢复只由后续 state 的 `triggered=false` 表示。

内部需求是 schema 2.0：`triggered` 表示已越过首次触发线，Social 额外支持
`URGENT`。signal 创建一次候选，state 的 `triggered` 负责相关性；等级变化会
移除仍在队列中的旧等级候选。

---

## 3. 上游链路详细拆解

### 3.1 情绪链路

```
emotion_engine_node
    │
    ├── /emotion/state (1Hz, BEST_EFFORT)
    │   ┌─────────────────────────────────────────────────────────┐
    │   │ {                                                       │
    │   │   "schema_version": "2.0",                              │
    │   │   "emotions": {                                         │
    │   │     "Joy":    { "value": 30, "triggerThreshold": 30,   │
    │   │                  "triggerOperator": "gte",              │
    │   │                  "triggered": true },                    │
    │   │     "Excite":  { "value": 20, "triggerThreshold": 40,   │
    │   │                  "triggerOperator": "gte",              │
    │   │                  "triggered": false },                   │
    │   │     "...":     {},                                      │
    │   │     "Calm":    { "value": 30, "triggerThreshold": 0,    │
    │   │                  "triggerOperator": "gte",              │
    │   │                  "triggered": true }                     │
    │   │   },                                                    │
    │   │   "triggered": [                                        │
    │   │     { "emotion": "Joy",                                 │
    │   │       "eventType": "EMO_JOY_TRIGGERED" },               │
    │   │     { "emotion": "Calm",                                │
    │   │       "eventType": "EMO_CALM_TRIGGERED" }               │
    │   │   ],                                                    │
    │   │   "dominantEmotion": "Joy"                              │
    │   │ }                                                       │
    │   └─────────────────────────────────────────────────────────┘
    │   处理: 要求 schema_version=2.0
    │         → 更新 emotion_states 的 value + triggered
    │         → 不生成候选；false 用于恢复和 RelevanceCondition
    │
    └── /emotion/signal_event (EVENT, RELIABLE)
        ┌─────────────────────────────────────────────────────────┐
        │ {                                                       │
        │   "schema_version": "2.0",                              │
        │   "event_type": "EMO_JOY_TRIGGERED",                    │
        │   "emotion": "Joy",                                     │
        │   "value": 30,                                          │
        │   "triggerThreshold": 30,                               │
        │   "triggerOperator": "gte"                              │
        │ }                                                       │
        └─────────────────────────────────────────────────────────┘
        处理流程:
          1. 校验 schema、精确 event_type 以及 emotion 一致性
          2. 同步最新 value + triggered=true 到黑板
          3. 异步调用 /perception/vision/task: check_person
               present=true  → visual_route=human, *WithHuman Behavior
               present=false → visual_route=solo, *Alone Behavior
          4. IntentMapper.map_emotion_event(event_type, value, visual_route)
          5. 查 config/emotion_behavior_map.yaml:
               human → expressJoyWithHuman, Lv5, variant=joy
               solo  → expressJoyAlone, Lv5, variant=joy
          6. 生成 BehaviorCandidate:
               behavior_name: "expressJoyWithHuman" | "expressJoyAlone"
               priority_level: 5 (EMOTION_EXPRESSION)
               sub_priority: 0
               interaction_mode: "interactive" | "solo"
               executor_behavior_name: "expressJoy" (下游兼容模板)
               cooldown_sec: 1.0 (Lv5 默认)
               timeout_sec: 8.0 (Lv5 默认)
               ttl_sec: 10.0
               interrupt_policy: "safe_point"
               dedup_key: ("emotion", "EMO_JOY_TRIGGERED", "expressJoyAlone", "joy", "solo")
               result_mapping: null (纯情绪表达不发布 /behavior/result_event)
          7. 经 CandidatePool.add() → 候选池

        如果 check_person 返回前 /emotion/state 已恢复 triggered=false，
        该迟到结果会被 generation 校验丢弃。

相关性校验 (RelevanceCondition):
  - 取 emotions["Joy"].triggered
  - true → SUCCESS，候选仍相关
  - false → FAILURE，情绪已恢复，候选被丢弃
```

### 3.2 需求链路

```
internal_need_node
    │
    ├── /internal_need/state (1Hz, BEST_EFFORT)
    │   ┌─────────────────────────────────────────────────────────┐
    │   │ {                                                       │
    │   │   "schema_version": "2.0",                             │
    │   │   "demands": {                                         │
    │   │     "Social": { "value": 71,                           │
    │   │       "triggerThreshold": 60, "triggerOperator": "gt",│
    │   │       "urgentThreshold": 70, "urgentOperator": "gt",  │
    │   │       "overflowThreshold": 85,                         │
    │   │       "triggered": true, "urgent": true,               │
    │   │       "overflow": false, "level": "URGENT",           │
    │   │       "levelEvent": "NEED_SOCIAL_URGENT",              │
    │   │       "levelActive": true }                             │
    │   │   }                                                     │
    │   │ }                                                       │
    │   └─────────────────────────────────────────────────────────┘
    │   处理: 校验 schema/value/阈值/level/flags
    │         → 更新 Blackboard.need_module
    │         → 不生成候选；清理已过期等级候选
    │
    └── /internal_need/signal_event (EVENT, RELIABLE)
        ┌─────────────────────────────────────────────────────────┐
        │ {                                                       │
        │   "schema_version": "2.0",                             │
        │   "event_type": "NEED_SOCIAL_URGENT",                  │
        │   "demand": "Social",                                  │
        │   "value": 71,                                          │
        │   "level": "URGENT",                                   │
        │   "previousLevel": "TRIGGERED",                        │
        │   "triggerThreshold": 60, "triggerOperator": "gt",    │
        │   "urgentThreshold": 70, "urgentOperator": "gt",      │
        │   "overflowThreshold": 85, "overflowOperator": "gt",  │
        │   "trigger": "LEVEL_CHANGED"                            │
        │ }                                                       │
        └─────────────────────────────────────────────────────────┘
        处理流程:
          1. 校验 schema、事件与 demand/level、严格 gt 阈值和 value 区间
          2. 同步最新 value/level/triggered/urgent/overflow 到黑板
          3. 删除该需求仍在排队的旧等级候选
          4. 异步调用 /perception/vision/task:
               check_person → present=true  → visual_route="human"
                            → present=false → detect_objects
               detect_objects 中有 cat/dog → visual_route="animal"
               无人且无 cat/dog → 不创建候选
          5. IntentMapper.map_need_event(
               "NEED_SOCIAL_URGENT",
               {"demand": "Social", "value": 71, "level": "URGENT"},
               visual_route="human" | "animal")
          6. 查 config/event_intent_map.yaml 的 routes:
               human  → seekInteraction / human_engage
               animal → greetAnimal / animal_greet
          7. 生成 BehaviorCandidate（以 human 路由为例）:
               behavior_name: "seekInteraction"
               priority_level: 4 (PSYCHOLOGICAL)
               sub_priority: 1
               cooldown_sec: 5.0 (Lv4 默认)
               timeout_sec: 25.0 (Lv4 默认)
               ttl_sec: 10.0
               interrupt_policy: "safe_point"
               dedup_key: ("need", "NEED_SOCIAL_URGENT",
                           "seekInteraction", "human_engage", "interactive")
               result_mapping: ("ACTION_ATTENTION_SEEK", "Social", ...)

        强度约束:
          - Social 的 TRIGGERED / URGENT / OVERFLOW 各自配置 human/animal Behavior
          - Bladder / Cleanliness / Exploration 到 100 仍是 TRIGGERED
          - Energy 是电量缺口，81=实际电量19%，91=实际电量9%
          - 未配置的 event_type 不生成候选
```

### 3.3 音频链路

```
perception_bridge
    │
    └── /perception/audio_event (EVENT, RELIABLE)
        ┌─────────────────────────────────────────────────────────┐
        │ {                                                       │
        │   "schema_version": 2,                                  │
        │   "event_type": "EVT_VOICE_COMMAND_SIT",                │
        │   "command_id": "CMD_SIT",                              │
        │   "dispatch_role": "specific_command",                  │
        │   "should_trigger_behavior_tree": true,                  │
        │   "intent_confidence": 0.95,                            │
        │   "asr_text": "坐下"                                     │
        │ }                                                       │
        └─────────────────────────────────────────────────────────┘

        白名单 (PerceptionClientAdapter):
          ✅ EVT_VOICE_WAKEUP         → respond_owner_call → 视觉解析 → 可选靠近
          ✅ 已审核的 EVT_VOICE_COMMAND_<ACTION>
             → 授权字段校验 → 专用 Behavior
          ✅ EVT_VOICE_COMMAND_PRAISE / SCOLD
             → social_reaction 授权 → Lv1 一次性原地社交反应
          ❌ EVT_VOICE_CALL_NAME / EVT_VOICE_COMMAND_CALL_NAME
             → 昵称社交语义，不创建会话或候选
          ❌ EVT_VOICE_PRAISE / SCOLD / HAPPY / SAD / NEUTRAL
             → 忽略，由 emotion_engine_node 消费
          ❌ EVT_VOICE_MASTER_ID / FOLK_ID / UNMASTER_ID / STRANGER_ID
             → 忽略，由 emotion_engine_node 消费

        处理流程:
          1. PerceptionClientAdapter._on_audio_ros2()
          2. schema v2 + 授权字段过滤 → 回调 ros_node._on_audio_direct()
          3. WAKEUP 创建 VoiceInteractionSession 并经 IntentMapper 生成
             respond_owner_call；命令事件也进入同一精确映射
          4. 查 config/event_intent_map.yaml → audio_direct section:
               EVT_VOICE_COMMAND_SIT:
                 category: external_interaction
                 intent: command_sit
                 expected_command_id: CMD_SIT
                 sub_priority: 1
             PRAISE/SCOLD 改查 audio_reaction section，不经 intent_action_pool；
             复用 emotion_behavior_map 中的行为名，但候选 source 仍为
             audio_reaction，不是 emotion。
          5. 查 config/intent_action_pool.yaml → command_sit:
               candidates: [sit_down]
          6. 生成 BehaviorCandidate:
               behavior_name: "sit_down"
               priority_level: 1 (EXTERNAL_INTERACTION)
               sub_priority: 1
               cooldown_sec: 1.0
               timeout_sec: 8.0
               ttl_sec: 8.0
               interrupt_policy: "immediate"
               dedup_key: ("audio_direct", "EVT_VOICE_COMMAND_SIT",
                           "sit_down", "", "solo")
```

**强指令约束**：WAKEUP 的 `respond_owner_call` 只负责原地转向，随后由
`wake_speaker_result → query_targets → approach_voice_caller → WAITING` 完成已识别
主人或家人的唤醒者接近；陌生人和未判定者原地等待。靠近由 Action 经
`locate_person_once → NavigateToPose` 执行一次固定导航目标。坐下、
趴下、站立、等待、过来、跟随、握手、击掌、翻滚、转圈、返回、吐掉和装死
都映射各自的专用 Behavior。

TOILET、CLEAN、SLEEP 是条件指令：在任何候选入池或会话修改之前分别要求
`Bladder > 50`、`Cleanliness > 40`、`Sleepiness > 50`，通过后复用
`barkShortAlert`、`lickPaws`、`sleepOnSide`。状态未初始化或等于阈值均不执行。

### 3.4 视觉链路

```
/emotion/signal_event
    └── EMO_*_TRIGGERED
          └── /perception/vision/task: check_person
                ├── 有人 → express* / interaction_mode=interactive
                └── 无人 → express* / interaction_mode=solo

/internal_need/signal_event
    │
    ├── NEED_HUNGER_TRIGGERED / OVERFLOW
    │     └── /perception/vision/task: detect_objects
    │           ├── 有狗粮 → eatNormally / eatExcitedly
    │           └── 无狗粮 → seekFood / seekFoodUrgently
    │
    ├── NEED_SOCIAL_TRIGGERED / URGENT / OVERFLOW
    │     └── /perception/vision/task
    │           1. check_person
    │              ├── present=true  → human 路由（人优先）
    │              └── present=false → 2. detect_objects
    │                                    ├── cat/dog → animal 路由
    │                                    └── 无       → 不生成候选
    │
    └── NEED_EXPLORATION_TRIGGERED
          └── /perception/vision/task: detect_objects
                ├── 拖鞋/袜子/玩具 → inspectFamiliarPlayItem
                ├── 垃圾桶         → inspectTrashCan
                ├── 快递盒子       → inspectDeliveryBox
                ├── 纸巾           → inspectTissuePaper
                ├── 门             → inspectDoor
                ├── 狗粮           → inspectDogFood
                ├── 陌生物品 → inspectObject
                └── 空场景   → exploreRoom

/perception/visual_event (10 Hz STATE SNAPSHOT, BEST_EFFORT)
    ├── 缓存 humans / active_target / tracked_objects
    ├── 视觉 Service 不可用时作为上述路由的回退
    ├── EVT_VISION_FALL → respond_person_fall (Lv1, sp=12)
    ├── EVT_VISION_STOP_GESTURE → respond_stop_gesture (Lv1, sp=12)
    └── 其余 events 不直接创建行为候选
```

服务类型优先使用 `marsdog_vision_interaction/srv/VisionTask`，接口名为
`/perception/vision/task`。如果运行环境只安装了旧接口，则兼容
`/perception/perception_task`；Standalone 使用 `MockPerceptionClient`。

---

## 4. 事件到候选的映射管道

### 4.1 配置文件映射链

```
事件输入
  │
  ├── 情绪事件: config/emotion_behavior_map.yaml
  │     EMO_JOY_TRIGGERED + human → expressJoyWithHuman
  │     EMO_JOY_TRIGGERED + solo  → expressJoyAlone
  │
  ├── 需求事件: config/event_intent_map.yaml (need section)
  │     NEED_HUNGER_TRIGGERED + dog_food
  │       → intent: eat_normal, behavior_name: eatNormally
  │     NEED_HUNGER_TRIGGERED + no_dog_food
  │       → intent: seek_food, behavior_name: seekFood
  │       └── config/intent_action_pool.yaml
  │             eat_normal → candidates: [eatNormally]
  │
  └── 音频事件: config/event_intent_map.yaml (audio_direct section)
        EVT_VOICE_COMMAND_SIT → intent: command_sit
          └── config/intent_action_pool.yaml
                command_sit → candidates: [sit_down]
```

### 4.2 BehaviorCandidate 数据结构

来自 [intent_mapper.py](../marsdog_behavior/intent_mapper.py#L45-L74):

| 字段 | 类型 | 说明 |
|------|------|------|
| `behavior_name` | str | 语义行为名（如 `expressJoyWithHuman`, `eatNormally`） |
| `source` | str | 来源类型: `audio_direct` / `need` / `emotion` / `idle` |
| `trigger_event` | str | 触发事件字符串（`EMO_JOY_TRIGGERED`, `EVT_VOICE_COMMAND_SIT` 等） |
| `intent` | str | 语义意图（`express_joy`, `command_sit` 等） |
| `priority_level` | int | 优先级 0-6（数字越小优先级越高） |
| `sub_priority` | int | 同级的二级优先级 |
| `intensity` | float | 0-100，用于同级抢占判断 |
| `level` | str | 需求等级；情绪使用 `LOW` 选择执行器动作池（不是 V1 事件等级） |
| `variant` | str | 变体（`joy`, `light`, `focused`） |
| `interactive` | bool | 是否交互模式 |
| `interaction_mode` | str | `solo` / `interactive` |
| `ttl_sec` | float | 候选存活时间，默认 **10.0 秒** |
| `cooldown_sec` | float | 执行后冷却时间（按 priority_level 默认值） |
| `timeout_sec` | float | 执行超时时间（按 priority_level 默认值） |
| `interrupt_policy` | str | `immediate` / `safe_point` / `non_interruptible` |
| `result_mapping` | dict | 需求行为的结果映射配置 |

### 4.3 去重键 (Dedup Key)

来自 [intent_mapper.py](../marsdog_behavior/intent_mapper.py#L79-L87):

```python
dedup_key = (source, trigger_event, behavior_name, variant, interaction_mode)
```

示例:
- 情绪: `("emotion", "EMO_JOY_TRIGGERED", "expressJoyAlone", "joy", "solo")`
- 需求: `("need", "NEED_HUNGER_TRIGGERED", "eatNormally", "food_visible", "solo")`
- 音频: `("audio_direct", "EVT_VOICE_COMMAND_SIT", "sit_down", "", "solo")`

复合 key 用于记录事件来源；另外按 `behavior_name` 做强唯一约束。同名行为只要
已经 queued 或 in-flight，即使来自不同事件或设置 `allow_repeat=true` 也不能
再次进入。TTL 过期会释放 queued key；被选中后转为 in-flight reservation，
直到对应 `candidate_id` 的终态到达。

### 4.4 默认冷却/超时 (按 priority_level)

来自 [intent_mapper.py](../marsdog_behavior/intent_mapper.py#L159-L166):

| Level | 名称 | cooldown_sec | timeout_sec |
|-------|------|-------------|-------------|
| 0 | System/Safety | 0.0s | 5.0s |
| 1 | ExternalInteraction | 1.0s | 8.0s |
| 2 | PhysioUrgent | 0.0s | 60.0s |
| 3 | PhysioNormal | 5.0s | 30.0s |
| 4 | Psychological | 5.0s | 25.0s |
| 5 | EmotionExpression | 1.0s | 8.0s |
| 6 | Idle | 0.0s | 30.0s |

---

## 5. 候选池 (CandidatePool)

### 5.1 数据结构

来自 [candidate_pool.py](../marsdog_behavior/candidate_pool.py):

```python
class CandidatePool:
    _candidates: list[dict]      # 候选队列
    _seen_keys: set[tuple]       # 去重键集合
    _inflight: dict[str, str]    # behavior_name → candidate_id
    _lock: threading.Lock        # 线程安全锁
```

### 5.2 生命周期

```
add()                              select_best()
  │                                   │
  │  1. discard_expired()             │  1. discard_expired()
  │  2. 拒绝同名 queued/in-flight     │  2. 排序并选择可运行候选
  │  3. 检查 dedup_key                │  3. pop queued key
  │  4. 加入 queue                    │  4. 建立 name → candidate_id reservation
  │                                   │
  ▼                                   ▼
  [QUEUED] ─────────────────────────> [IN_FLIGHT]
  │                                   │
  ├── TTL/权威状态失效 → 释放          ├── 终态 → release_inflight()
  └── 未被选中 → 继续等待              └── 未实际 dispatch → 立即释放
```

`allow_repeat` 只允许前一轮终态之后重新加入，不绕过 queued、in-flight 或
post-completion cooldown。释放时校验 `candidate_id`，迟到的旧终态不能释放同名
的新一轮执行。

### 5.3 冷却中的候选

- 冷却中的候选**不丢弃**，继续留在池中
- 每次 `select_best()` 跳过冷却中的候选选择下一个
- 冷却结束后，该候选可以在后续 tick 中被选中
- 如果 TTL 在冷却期间过期，候选被丢弃，释放去重键

### 5.4 未选中候选

- 未被选中的候选也**保留在池中**
- 下一个 tick 继续参与排序和选择
- 直到 TTL 过期或优先级更高的候选出现

---

## 6. 行为树结构

### 6.1 树拓扑

来自 [tree_builder.py](../bionic_dog_bt/tree_builder.py):

```
Root (Selector, memory=False, 每 tick 从 Lv0 重新评估)
├── Seq_Lv0_System
│   ├── ActiveLevelCondition(level=0)       ← 检测该层是否有活跃/运行中的行为
│   ├── BehaviorRelevanceCondition          ← 情绪/需求 triggered 相关性
│   └── ExecuteActiveBehavior              ← 下发 Goal / 监控 / 抢占 / 超时
├── Seq_Lv1_ExternalInteraction
│   ├── ActiveLevelCondition(level=1)
│   ├── BehaviorRelevanceCondition
│   └── ExecuteActiveBehavior
├── Seq_Lv2_PhysioUrgent
│   ├── ActiveLevelCondition(level=2)
│   ├── BehaviorRelevanceCondition
│   └── ExecuteActiveBehavior
├── Seq_Lv3_PhysioNormal
│   ├── ActiveLevelCondition(level=3)
│   ├── BehaviorRelevanceCondition
│   └── ExecuteActiveBehavior
├── Seq_Lv4_Psychological
│   ├── ActiveLevelCondition(level=4)
│   ├── BehaviorRelevanceCondition
│   └── ExecuteActiveBehavior
├── Seq_Lv5_EmotionExpression
│   ├── ActiveLevelCondition(level=5)
│   ├── BehaviorRelevanceCondition
│   └── ExecuteActiveBehavior
└── Seq_Lv6_Idle
    ├── ActiveLevelCondition(level=6)
    ├── BehaviorRelevanceCondition
    └── ExecuteActiveBehavior
```

### 6.2 节点类型说明

| 节点 | 类型 | 说明 |
|------|------|------|
| `Root` | Selector (memory=False) | 每 tick 从第一个子节点（Lv0）重新评估，保证高优先级总是被检查 |
| `Seq_LvX` | Sequence | 三个子节点必须全部 SUCCESS 才会执行该层行为 |
| `ActiveLevelCondition` | Condition | 检查 `active_behavior.priority_level == level` 或 `current_behavior` 正在该层运行 |
| `BehaviorRelevanceCondition` | Condition | 情绪和需求都检查当前 triggered |
| `ExecuteActiveBehavior` | Action | 核心执行节点：下发 Goal、抢占、超时、冷却、结果处理 |

### 6.3 ActiveLevelCondition

来自 [conditions.py](../bionic_dog_bt/conditions.py#L23-L52):

```python
SUCCESS 条件:
  1. bb.active_behavior 存在 且 priority_level == self.level
  2. bb.current_behavior 存在 且 status == RUNNING 且 priority_level == self.level

FAILURE:
  - 以上两者都不满足
```

**关键**: 即使 active_behavior 已被 ExecuteActiveBehavior 消费，只要 current_behavior 仍在运行且 level 匹配，该条件仍然返回 SUCCESS。这保证了 Selector 能正确将执行权交给正在运行的层。

### 6.4 BehaviorRelevanceCondition

来自 [conditions.py](../bionic_dog_bt/conditions.py#L55-L168):

**情绪类行为校验**:
```python
if bb.emotion_module.is_triggered("Joy"):
    → SUCCESS
else:
    → FAILURE (情绪已恢复, 丢弃候选)
```

**需求类行为校验**:
```python
need_name = active.params["source_need"]
if bb.need_module.is_triggered(need_name):
    → SUCCESS
else:
    → FAILURE (需求已恢复)
```

**其他类型** (system, external, idle): 始终 SUCCESS。

### 6.5 ExecuteActiveBehavior - 执行状态机

来自 [actions.py](../bionic_dog_bt/actions.py#L50-L199):

```
update() 每次 tick 的执行流程:

1. executor.tick()           ← 推进模拟/异步通信
2. 检查真实 Result            ← Result 到达后才进入 TERMINAL 并释放执行权
3. CANCEL_REQUESTED         ← 保留旧 Goal/锁/映射/待替代候选，继续等待 Result
4. 检查超时                   ← 记录 timeout_requested + 请求取消，不伪造终态
5. 无 active_behavior       ← 继续等当前行为
6. 检查冷却                   ← 冷却中→丢弃候选
7. 无当前行为                  → send_goal
8. 同行为名+运行中            → 丢弃重复候选
9. 抢占评估                   → 见 6.6 节
10. 执行抢占                  → 请求取消旧 Goal，真实终态后再 send 新 Goal
```

Goal 生命周期为 `SENDING → RUNNING → CANCEL_REQUESTED → TERMINAL`。
`cancel_goal_async()` 返回或取消请求被受理只表示 `CANCEL_REQUESTED`；只有
`/execute_behavior` 的真实 Result 可以进入 `TERMINAL`。因此取消期间不会清除
`current_goal_id`、Goal Handle、Future、in-flight reservation，也不会生成本地
`CANCELED`/`TIMEOUT` 结果。

**check_person（情绪视觉分流）**:
- 收到六类 `EMO_*_TRIGGERED` 后，由 ROS2 入口异步调用视觉 Service
- 有人 → 生成 `*WithHuman`，携带人物 target 和 `mode="interactive"`
- 没人 → 生成 `*Alone`，设置 `mode="solo"`
- Service 结果返回前如果情绪恢复，generation 校验会丢弃迟到结果
- 执行阶段使用已经解析好的视觉分支，不再重新读取人物缓存覆盖 Service 结果

### 6.6 抢占规则

来自 [arbitration.py](../bionic_dog_bt/arbitration.py):

```python
def evaluate_preemption(active_priority, active_value, active_name,
                        current_priority, current_value, current_policy,
                        executor_feedback):

    # 规则 1: 更低 level → 更高优先级 → 可以抢占
    if active_priority < current_priority:
        return check_interrupt_policy(...)

    # 规则 2: 同级 → 需要强度差 >= 15
    if active_priority == current_priority:
        delta = active_value - current_value
        if delta >= 15:
            return check_interrupt_policy(...)
        return False  # 强度不够

    # 规则 3: 更高 level → 不抢占
    return False
```

**中断策略**:

| 策略 | 行为 | emergency_stop 可覆盖 |
|------|------|----------------------|
| `immediate` | 最新 Feedback 必须 `safe_to_interrupt=true` 才请求取消 | 是 |
| `safe_point` | 最新 Feedback 必须 `safe_to_interrupt=true` 才请求取消 | 是 |
| `non_interruptible` | 不中断 | **是**（唯一例外） |

`DISPATCHED` 和 `RECOVERY_REQUIRED` 一律视为不可中断。`emergency_stop` 可立即
发出取消请求，但同样必须等旧 Goal 的真实 Result 后才能释放导航锁并发送自身 Goal。

### 6.7 优先级常量

来自 [constants.py](../bionic_dog_bt/constants.py):

| Level | 名称 | 说明 | 典型行为 |
|-------|------|------|---------|
| 0 | SYSTEM | 系统安全 | emergency_stop, avoid_danger |
| 1 | EXTERNAL_INTERACTION | 外部交互 | sit_down, follow_owner, give_paw, respond_owner_call |
| 2 | PHYSIO_URGENT | 紧急生理 | barkShortAlert, sleepOnSide, sleepNow |
| 3 | PHYSIO_NORMAL | 常规生理 | 进食/找食物、清洁 |
| 4 | PSYCHOLOGICAL | 心理需求 | 人/动物社交、熟悉/陌生物品检查、空间探索 |
| 5 | EMOTION_EXPRESSION | 情绪表达 | 6 个 V2 事件按有人/语音等待原地/无人分成 18 个语义 Behavior |
| 6 | IDLE | 空闲 | idle_look_around, idle_rest |

---

## 7. 下游连接：行为执行与结果回传

### 7.1 Action Client: /execute_behavior

**Goal 消息** ([interfaces.py](../marsdog_behavior/interfaces.py#L183-L213)):

```json
{
  "goal_id": "goal_a1b2c3d4e5f6",
  "behavior_id": "bhv_xxxxxxxxxxxx",
  "behavior_name": "expressJoy",
  "priority_level": 5,
  "params_json": "{\"source\":\"emotion\",\"trigger_event\":\"EMO_JOY_TRIGGERED\",\"executor_behavior_name\":\"expressJoy\",...}",
  "timeout_sec": 8.0
}
```

此处 Action Goal 的 `behavior_name=expressJoy` 是执行端兼容模板。行为树内部
保存的请求名为 `expressJoyWithHuman` 或 `expressJoyAlone`；适配器收到反馈后
会恢复为请求名。

**Feedback 消息** ([interfaces.py](../marsdog_behavior/interfaces.py#L215-L237)):

```json
{
  "goal_id": "goal_a1b2c3d4e5f6",
  "behavior_id": "bhv_xxxxxxxxxxxx",
  "behavior_name": "expressJoyWithHuman",
  "status": "RUNNING",
  "progress": 0.5,
  "safe_to_interrupt": true,
  "current_action": "wag_tail",
  "message": ""
}
```

**Result 消息** ([interfaces.py](../marsdog_behavior/interfaces.py#L239-L264)):

```json
{
  "goal_id": "goal_a1b2c3d4e5f6",
  "behavior_id": "bhv_xxxxxxxxxxxx",
  "behavior_name": "spinInCircle",
  "status": "SUCCESS",
  "result": "completed",
  "reason": "",
  "reward": 1.0,
  "emotion_delta_json": "{\"Joy\": -15}",
  "need_delta_json": "{}"
}
```

### 7.2 行为执行配置 (behaviors.yaml)

每个行为定义包含动作序列，示例:

```yaml
express_happy:
  priority_level: 5
  base_priority: 50
  interrupt_policy: immediate
  timeout_sec: 5.0
  cooldown_sec: 1.0
  action_sequence:
    - node: head_tail_ear
      action: wag_tail
      duration: 1.5
      safe_to_interrupt: true
    - node: posture
      action: play_bow
      duration: 1.0
      safe_to_interrupt: true
    - node: vocalization
      action: happy_bark
      duration: 0.5
      safe_to_interrupt: true
  style_modifiers:
    happy:
      tail_wag: fast
      ear_pose: raised
      voice_tone: excited
```

**动作节点类型**: `full_body`, `posture`, `head_tail_ear`, `vocalization`, `navigation`, `perception`

### 7.3 发布: /behavior/result_event

来自 [result_event_mapper.py](../marsdog_behavior/result_event_mapper.py):

**仅发布需求行为** (在 `BEHAVIOR_ACTION_MAP` 中的行为):

| behavior_name | action_type | demand_type |
|---|---|---|
| eatNormally | ACTION_EAT | Hunger |
| eatExcitedly | ACTION_EAT | Hunger |
| seekFood | ACTION_FOOD_SEEK | Hunger |
| seekFoodUrgently | ACTION_FOOD_SEEK | Hunger |
| barkShortAlert | ACTION_DEFECATE | Bladder |
| sleepOnSide | ACTION_SLEEP | Sleepiness |
| sleepNow | ACTION_SLEEP | Sleepiness |
| lickPaws | ACTION_GROOM | Cleanliness |
| restInPlace | ACTION_RECHARGE | Energy |
| recharge | ACTION_RECHARGE | Energy |
| seekHumanInteraction | ACTION_ATTENTION_SEEK | Social |
| testAnimalBoundary | ACTION_BOUNDARY_TEST | Social |
| seekInteraction | ACTION_ATTENTION_SEEK | Social |
| greetAnimal | ACTION_SOCIAL_GREET | Social |
| inviteHumanToPlay | ACTION_PLAY_INVITE | Social |
| inviteAnimalToPlay | ACTION_PLAY_INVITE | Social |
| inspectFamiliarPlayItem | ACTION_OBJECT_EXPLORE | Exploration |
| inspectTrashCan | ACTION_OBJECT_EXPLORE | Exploration |
| inspectDeliveryBox | ACTION_OBJECT_EXPLORE | Exploration |
| inspectTissuePaper | ACTION_OBJECT_EXPLORE | Exploration |
| inspectDoor | ACTION_OBJECT_EXPLORE | Exploration |
| inspectDogFood | ACTION_OBJECT_EXPLORE | Exploration |
| inspectObject | ACTION_OBJECT_EXPLORE | Exploration |
| exploreRoom | ACTION_SPACE_EXPLORE | Exploration |

**纯情绪表达行为（如 `expressJoyWithHuman`、`expressFearAlone`）不发布需求结果。**

**Status 映射**:

| 内部状态 | 发布 result_type |
|---------|-----------------|
| SUCCESS | COMPLETED |
| FAILURE | FAILED |
| TIMEOUT | TIMEOUT |
| CANCELED | INTERRUPTED |

**STARTED 事件**:
- 行为开始时也发布一个 `result_type: "STARTED"` 的事件

**消息格式**:

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

### 7.4 结果反馈闭环

```
action_executor Result
  → BehaviorFeedbackEvent (actions.py:108-113)
    → bb.last_feedback_event
      → BehaviorRuntime.tick() 读取 (runtime.py:70-71)
        → TickOutcome.completed_event
          → BehaviorTreeRosNode 的 tick 回调
            → ResultEventMapper.build_result_event()
              → /behavior/result_event 发布
            → ResultEventMapper.build_started_event()
              → /behavior/result_event 发布 (行为开始时)

同时:
  → bb.set_cooldown(behavior_name, cooldown_sec)
    → 防止短期内重复执行同一行为
```

---

## 8. Tick 循环完整流程

来自 [BehaviorRuntime.tick()](../marsdog_behavior/runtime.py#L54-L78) 和 [ExecuteActiveBehavior.update()](../bionic_dog_bt/actions.py#L75-L199):

```
每个 tick (100ms):

┌── BehaviorRuntime.tick() ──────────────────────────────────────────┐
│                                                                     │
│  1. candidate = candidate_pool.select_best(blackboard)              │
│     ├── discard_expired() — 丢弃 TTL 过期的候选                      │
│     ├── sort: level ASC → sub_priority ASC → value DESC             │
│     │         → created_at DESC                                     │
│     └── 选第一个不在冷却中的候选                                       │
│                                                                     │
│  2. if candidate:                                                   │
│       blackboard.set_active_behavior(                              │
│         candidate_to_active_behavior(candidate))                   │
│                                                                     │
│  3. tree.reset()  — Selector 从 Lv0 重新评估                        │
│  4. tree_status = tree.tick()                                      │
│     │                                                               │
│     ├── Root Selector (memory=False) 从 Lv0 开始                      │
│     │                                                               │
│     ├── Seq_Lv0:                                                    │
│     │   ├── ActiveLevelCondition(0) → active level 匹配?            │
│     │   ├── BehaviorRelevanceCondition → 情绪/需求仍相关?             │
│     │   └── ExecuteActiveBehavior.update():                         │
│     │       ├── executor.tick()                                     │
│     │       ├── check_result → 真实终态后 cooldown + 释放执行权       │
│     │       ├── check_timeout → timeout_requested + 请求 cancel      │
│     │       ├── no active_behavior → 更新 feedback, return RUNNING   │
│     │       ├── is_in_cooldown → 丢弃候选                              │
│     │       ├── no current → send_goal + RUNNING                    │
│     │       ├── same name running → 丢弃重复                           │
│     │       ├── can_preempt? → cancel 旧，等待真实 Result             │
│     │       ├── old TERMINAL → 再 send 保留的新候选                    │
│     │       └── can't preempt → 丢弃候选, 继续当前                     │
│     │                                                               │
│     └── 如果 Lv0 FAILURE → Selector 尝试 Lv1 → Lv2 → ... → Lv6     │
│                                                                     │
│  5. 观察 STARTED: 如果 current_behavior 有新的 goal_id               │
│       → TickOutcome.started_behavior                                │
│       → ResultEventMapper.build_started_event()                     │
│       → /behavior/result_event (STARTED)                            │
│                                                                     │
│  6. 观察终态: 如果 last_feedback_event 非空                          │
│       → TickOutcome.completed_event                                │
│       → ResultEventMapper.build_result_event()                      │
│       → /behavior/result_event (COMPLETED/FAILED/...)               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 9. 黑板 (Blackboard) 状态

来自 [blackboard.py](../bionic_dog_bt/blackboard.py):

| 字段 | 类型 | 说明 |
|------|------|------|
| `active_behavior` | ActiveBehavior | 候选池选出的待执行行为 |
| `current_behavior` | ActiveBehavior | 当前正在执行的行为 |
| `current_status` | str | 当前行为状态: RUNNING / SUCCESS / FAILURE |
| `current_goal_id` | str | 执行器 goal_id |
| `executor_feedback` | ExecutorFeedback | 执行器反馈 |
| `last_feedback_event` | BehaviorFeedbackEvent | 最近完成的行为反馈 |
| `cooldown_until` | dict[str, float] | 行为名 → 冷却结束时间戳 |
| `preemption_occurred` | bool | 当前 tick 是否发生抢占 |
| `tick_count` | int | 总 tick 次数 |
| `emotion_module` | EmotionModule | 情绪 V2 数值 + triggered |
| `need_module` | NeedModule | 需求 V2 阈值、level 和 triggered/urgent/overflow |
| `perception_client` | PerceptionClient | 感知客户端 (check_person 等) |

---

## 10. 配置文件全景

| 文件 | 作用 | 关键映射 |
|------|------|---------|
| [config/behaviors.yaml](../config/behaviors.yaml) | 行为定义：优先级、动作序列、冷却、超时、风格 | behavior_name → ActionSequence |
| [config/event_intent_map.yaml](../config/event_intent_map.yaml) | 事件到意图的映射 | audio_direct/need/emotion event → intent |
| [config/emotion_behavior_map.yaml](../config/emotion_behavior_map.yaml) | 情绪事件到行为名 | EMO_* → behavior_name + variant |
| [config/intent_action_pool.yaml](../config/intent_action_pool.yaml) | 意图到候选行为池 | intent → candidates[]（旧输入别名由独立表管理） |
| [config/behavior_categories.yaml](../config/behavior_categories.yaml) | 7 层行为分类定义 | category → priority_level |
| [config/legacy_behavior_aliases.yaml](../config/legacy_behavior_aliases.yaml) | 旧行为名到新语义名的别名 | old_name → new_name |

---

## 11. 关键时间参数总结

| 参数 | 默认值 | 作用域 | 说明 |
|------|-------|--------|------|
| `ttl_sec` | **10.0s** | BehaviorCandidate | 候选在池中的存活时间，过期后释放去重键 |
| `cooldown_sec` | 0.0 ~ 5.0s | 每个行为 (behaviors.yaml) | 行为执行完成后禁止重新执行的冷却时间 |
| `timeout_sec` | `0` 或有限秒数 | 每个行为 (behaviors.yaml) | `0` 表示 Tree 外层无截止时间；长期 Goal 仍要求 Action 内部步骤有有限超时 |
| `tick_rate` | **100ms** | BehaviorTreeRosNode | BT 评估频率 |
| `SAME_LEVEL_PREEMPTION_DELTA` | **15** | 常量 | 同级抢占所需的最小强度差值 |
| `/emotion/state` | **1Hz** | 上游 | 情绪状态发布频率 |
| `/internal_need/state` | **1Hz** | 上游 | 需求状态发布频率 |

---

## 12. 目录与模块依赖

```
入口层:
  marsdog_behavior/ros_node.py          ← ROS2 节点 (订阅/发布/Timer)
  marsdog_behavior/standalone_demo.py   ← 无 ROS2 的独立演示
  bionic_dog_bt/demo.py                ← 纯 BT 演示

适配层 (marsdog_behavior/):
  intent_mapper.py                      ← 事件 → 候选转换
  candidate_pool.py                     ← 候选去重/排序/选择
  runtime.py                            ← 仲裁编排 + BT tick
  behavior_selector.py                  ← 候选选择 (standalone 用)
  perception_client_adapter.py          ← 感知 ROS2 适配
  action_client_adapter.py              ← Action Client ROS2 适配
  execution_manager.py                  ← 行为执行生命周期管理
  result_event_mapper.py                ← 结果映射到 /behavior/result_event
  interfaces.py                         ← ROS2 消息对应的 dataclass
  config_paths.py                       ← 配置文件路径解析

纯运行时 (bionic_dog_bt/):
  behavior_tree_node.py                 ← BT 基类 (Node, Selector, Sequence)
  actions.py                            ← ExecuteActiveBehavior 执行节点
  conditions.py                         ← ActiveLevelCondition, RelevanceCondition
  decorators.py                         ← Inverter, CooldownDecorator
  arbitration.py                        ← 抢占规则 (纯函数)
  blackboard.py                         ← 共享状态
  datatypes.py                          ← 核心数据类型
  constants.py                          ← 优先级/状态/阈值常量
  tree_builder.py                       ← 树构建
  emotion_module.py                     ← 情绪状态管理
  need_module.py                        ← 需求状态管理
  yaml_loader.py                        ← behaviors.yaml 加载

配置:
  config/behaviors.yaml                 ← 行为定义
  config/event_intent_map.yaml          ← 事件→意图映射
  config/emotion_behavior_map.yaml      ← 情绪→行为映射
  config/intent_action_pool.yaml        ← 意图→候选池
  config/behavior_categories.yaml       ← 分类定义
  config/legacy_behavior_aliases.yaml   ← 兼容别名
```

---

## 13. 依赖方向

```
ROS2 入口 / standalone 入口
        ↓
marsdog_behavior 适配层 (IntentMapper, CandidatePool, Runtime, ActionClientAdapter)
        ↓
bionic_dog_bt 纯运行时 (无 ROS2 依赖)
```

`bionic_dog_bt` 不依赖 ROS2 或 `marsdog_behavior`，可独立测试。所有 ROS2 消息解析、Action/Service 类型留在适配层。

---

## 14. 测试与调试

```bash
# 查看行为树完整 tick 日志 (rich table)
uv run python -m bionic_dog_bt.demo

# 查看事件 → 行为链路 (独立模式)
uv run python -m marsdog_behavior.standalone_demo

# ROS2 调试
ros2 topic echo /behavior/result_event    # 行为结果
ros2 topic echo /emotion/signal_event     # 情绪事件
ros2 topic echo /internal_need/signal_event  # 需求事件

# 手动注入测试事件
ros2 topic pub --once /perception/audio_event std_msgs/msg/String \
  "{data: '{\"schema_version\":2,\"event_type\":\"EVT_VOICE_COMMAND_SIT\",\"interaction_id\":\"manual-1\",\"utterance_id\":\"manual-u1\",\"command_id\":\"CMD_SIT\",\"specific_event_type\":\"EVT_VOICE_COMMAND_SIT\",\"dispatch_role\":\"specific_command\",\"should_trigger_behavior_tree\":true,\"intent_confidence\":0.95,\"slots\":[]}'}"

ros2 topic pub --once /emotion/signal_event std_msgs/msg/String \
  "{data: '{\"schema_version\":\"2.0\",\"event_type\":\"EMO_JOY_TRIGGERED\",\"emotion\":\"Joy\",\"value\":30,\"triggerThreshold\":30,\"triggerOperator\":\"gte\"}'}"
```
