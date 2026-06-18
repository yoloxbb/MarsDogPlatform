# MarsDog感知理解层 → ROS2 输出规范

> 感知理解层。内部可拆分多个 ROS2 Node，但下游只订阅两个 topic + 一个 service。

## 一、整体架构

```
┌── 感知理解层 (内部多 Node，对外统一接口)  ───────────────────────┐
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐     │
│  │ wakeup   │  │  audio   │  │  vision   │  │  intent   │     │
│  │ (MCU)    │  │ (VAD/ASR │  │ (face/    │  │ (rule/    │     │
│  │          │  │ /Speaker)│  │  human/   │  │  LLM)     │     │
│  │          │  │          │  │  hand/    │  │           │     │
│  │          │  │          │  │  object)  │  │           │     │
│  └────┬─────┘  └────┬─────┘  └────┬──────┘  └─────┬─────┘     │
│       │              │             │                │         │
│       └──────────────┴──────┬──────┴────────────────┘         │
│                             │                                 │
│              ┌──────────────┴──────────────┐                  │
│              │     perception_bridge       │ ← 对外唯一出口    │
│              └──────────────┬──────────────┘                  │
│                             │                                 │
└─────────────────────────────┼─────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
     /perception         /perception      /dog
     /observation        /interaction     /perception_task
     (topic, ~10Hz)      _event (topic)   (service)
              │               │               │
              ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                      ROS2 下游 (执行层)                      │
│                                                             │
│   behavior_tree ──→ 决策中心，消费 observation + event       │
│        │             按需调用 /dog/perception_task          │
│        ▼                                                    │
│   motion_planner / gait_controller / task_executor          │
└─────────────────────────────────────────────────────────────┘
```

**原则：**
- 内部可拆任意多个 Node（wakeup / audio / vision / intent / state），方便调试和独立升级
- 对外只暴露 `perception_bridge` 这一个 Node 的两个 topic 和一个 service
- 按需感知（如物体识别）由 behavior_tree 通过 service 触发，不做成常驻 topic

---

## 二、对外接口

### 2.1 Topic `/perception/observation`

常驻流，~5-10 Hz，Best Effort。发布持续感知到的环境信息。

```yaml
std_msgs/Header header           # stamp + frame_id

# ── 人脸 ──
Face[] faces
  float64 x y w h
  float64 confidence
  string recognized_user

# ── 人体 ──
Human[] humans
  float64 x y w h
  float64 confidence
  string pose_state
  Keypoint[] keypoints
    int32 id
    float64 x y
    float64 confidence

# ── 手势 ──
Hand[] hands
  string handedness
  Landmark[] landmarks          # 手部关键点
    int32 id
    float64 x y                 # 归一化坐标

# ── 持续跟踪的物体 (可选，默认关闭) ──
TrackedObject[] tracked_objects
  string label
  float64 x y w h
  float64 confidence
  float64 center_x center_y
```

> 这是"机器人持续看到了什么"的流。不含一次性事件（唤醒、语音指令等），也不含重量级按需检测（如 YOLOE-seg 全图物体搜索）。

### 2.2 Topic `/perception/interaction_event`

离散事件，按需发布，Reliable。每一次人机交互触发一条消息。

```yaml
std_msgs/Header header

string event_type                # 事件类型

# ── 以下字段按 event_type 选择性填充 ──

# wakeup 类
string wake_word
float64 wake_angle
float64 wake_confidence

# speech 类
string asr_text
string speaker_id
float64 speaker_confidence
string emotion
string language

# intent 类
string command_id
string intent_category
string intent_source             # 规则 / 本地LLM / 在线LLM
float64 intent_confidence
Slot[] slots
  string key
  string value
string response_text
bool is_executable

# danger 类
string danger_type
float64 danger_angle

# state 类
string state
string previous_state
string state_reason

# 通用
float64 latency_ms               # 该事件的感知管线延迟
```

> 一条 interaction_event 代表一次完整的人机交互回合。例如用户说"坐下"后会依次产生 `wakeup` → `speech` → `intent` 三条 event。下游 behavior_tree 根据 event_type 路由到对应的处理分支。

### 2.3 Service `/dog/perception_task`

下游（behavior_tree）按需触发感知任务。同步调用，感知层执行完成后返回结果。

```yaml
# Request
string task_id                   # 一次任务唯一标识
string task_type                 # 任务类型
Slot[] params                    # 任务参数
---
# Response
bool success
string task_id                   # 回传
string task_type
Slot[] result                    # 结果数据
string error_message
float64 latency_ms
```

**task_type 示例（由 behavior_tree 驱动）：**

| task_type | 说明 | params | result |
|---|---|---|---|
| `detect_objects` | 全图物体搜索 | `confidence`, `classes` | `objects[]` 检测结果 |
| `enroll_face` | 录入人脸 | `user_id`, `image_data` | `success` |
| `recognize_face` | 按需人脸识别 | `image_data` | `user_id`, `confidence` |
| `enroll_speaker` | 录入声纹 | `user_id`, `audio_samples` | `success` |
| `verify_speaker` | 按需声纹验证 | `audio_samples` | `speaker_id`, `confidence` |
| `check_person` | 确认是否有人在视野内 | — | `present`, `count` |

> 常驻 topic `/perception/observation` 已经在持续做人脸检测和人体检测，`detect_objects` 这类重量级任务只在 behavior_tree 明确需要时才触发（例如 intent 为 `CMD_BRING_OBJECT` 时）。

---

## 三、典型交互流程

### 3.1 语音指令 → 执行

```
observation:  一直在推 faces/humans/hands @ 10Hz (被动感知)

interaction_event {event_type: "wakeup", wake_word: "...", angle: 85}
interaction_event {event_type: "speech", asr_text: "把红球拿给我", speaker_id: "张三"}
interaction_event {event_type: "intent", command_id: "CMD_BRING_OBJECT",
                   slots: [{key: "object_name", value: "红球"}]}

BT 分析: command_id = CMD_BRING_OBJECT, 物体未定位
  → 调用 /dog/perception_task {task_type: "detect_objects", params: [{confidence: 0.3}]}
  ← {success: true, result: [{label: "red ball", center: (0.35, 0.6)}, ...]}

BT: 选择红球, 下达 CMD_APPROACH → motion_planner
  → 过程中持续读 observation.objects 做视觉伺服
```



---

## 四、内部 Node 拆分建议

对外两个 topic + 一个 service 由 `perception_bridge` 统一发布。内部可按需拆分为：

```
/perception/observation       ← vision_node (camera + YuNet + YOLO + MediaPipe)
/perception/interaction_event ← audio_node (VAD + ASR + Speaker)
                              ← intent_node (rule + LLM, 消费 audio_node 输出)
                              ← wakeup_node (MCU 串口)
                              ← state_node (状态机)
/dog/perception_task          ← perception_bridge (转发 + 按需触发 object detect)
```

内部 Node 之间的通信方式（topic/service/action）是实现细节，不在本文档定义范围。对外保证两个 topic + 一个 service 的接口稳定即可。

---



---

## 五、坐标系

| 域 | 约定 |
|---|---|
| 像素坐标 | 左上角原点, `camera_link` frame |
| 归一化坐标 | [0, 1], 基于图像宽高 |
| 声源角度 | 0° = 正前方, `base_link` frame |
| 关键点 | 按各自模型定义的索引顺序 |

3D 转换由下游负责。

---

## 七、注意事项

1. 感知层不做动作决策——intent 给出 `command_id + slots`，由 behavior_tree 决定是否执行、如何执行
2. 按需感知通过 `/dog/perception_task` service 触发，不做成 topic（避免无任务时浪费 NPU）
3. `/perception/observation` 发布常驻的轻量检测（face/human/hand），默认不跑 YOLOE-seg 全图物体搜索
4. `/perception/interaction_event` 的 `event_type` 字段是路由键，下游 switch 分发
5. 内部 Node 拆分自由，只要对外接口不变

---

## 八、当前行为系统适配

当前仓库中的 `marsdog_ros2.behavior_node` 已按本文档订阅：

- `/perception/observation`
- `/perception/interaction_event`

第一阶段尚未生成正式 ROS2 自定义 msg/srv，因此这两个 topic 暂时使用 `std_msgs/String` 承载 JSON，JSON 字段名与本文档保持一致。后续替换为正式消息类型时，`marsdog_ros2/perception_adapter.py` 的字段映射可继续复用。

### 8.1 observation 映射

| 输入字段 | 核心事件 |
|---|---|
| `faces[]` 或 `humans[]` 非空 | `HumanApproach` |
| `tracked_objects[]` 非空 | `NewObject` |

### 8.2 interaction_event 映射

| `event_type` | 条件 | 核心事件 / 状态 |
|---|---|---|
| `wakeup` | 任意 | `OwnerCall` |
| `speech` | 任意 | `VoiceInput` |
| `intent` | `command_id` 属于主人交互类 | `OwnerCall` |
| `intent` | 其他命令 | `Intent` |
| `danger` | `danger_type=weightlessness/free_fall/falling` | `Weightlessness` |
| `danger` | `danger_type=pain/hit/collision/impact` | `Pain` |
| `danger` | 其他危险 | `Danger` |
| `state` | `state=lights_off/light_off/dark/关灯` | `SetLightsOffValue(True)` 并立即刷新 `Sleepiness` |
| `state` | `state=lights_on/light_on/bright/开灯` | `SetLightsOffValue(False)` |
