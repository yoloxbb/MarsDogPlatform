# MarsDog Behavior — 仿生机器狗行为决策引擎

基于优先级行为树的仿生机器狗行为决策引擎。纯 Python 行为树框架 (bionic_dog_bt) + ROS2 节点层 (marsdog_behavior)。

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│ 上游 ROS2 节点（独立运行）                                     │
│                                                              │
│  emotion_engine_node    → /emotion/state (1Hz)                │
│                         → /emotion/signal_event              │
│  internal_need_node     → /internal_need/state (1Hz)          │
│                         → /internal_need/signal_event        │
│  perception_bridge      → /perception/audio_event             │
│                         → /perception/visual_event            │
│                         ← /perception/perception_task         │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ marsdog_behavior — 本项目（行为树决策引擎）                      │
│                                                              │
│  事件 → intent → behavior 管道：                                │
│    audio_direct: EVT_VOICE_CALL_NAME / EVT_VOICE_COMMAND_KNOWN │
│    need:         NEED_*_TRIGGERED / OVERFLOW                   │
│    emotion:      EMO_*_LOW / MID / HIGH                        │
│                                                              │
│  候选池 → 行为选择 → BT tick (7层)                              │
│  情绪/需求行为：字符串比对 levelEvents vs trigger_event          │
│  执行时：check_person → interactive / solo                    │
│  Action Client → /execute_behavior                            │
│  发布 → /behavior/result_event                                │
│                                                              │
│  visual_event: 仅用于 active_target 缓存，不生成行为候选        │
│  其他 audio_event: IGNORED → 由 emotion_engine 消费            │
│                                                              │
│  内部模块：                                                    │
│    bionic_dog_bt/        — 纯 Python 行为树框架                 │
│    marsdog_behavior/     — ROS2 节点层（薄壳）                  │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ marsdog_action_executor — 独立下游项目                          │
│  Action Server: /execute_behavior                             │
│  维护具体动作序列 (action_catalog)                              │
│  Goal → Feedback(progress/action) → Result                    │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ marsdog_interfaces — 公共接口包（独立）                          │
│  action/ExecuteBehavior.action                                │
│  msg/EmotionState, NeedState, AudioEvent, VisualEvent, ...     │
│  srv/PerceptionTask.srv                                       │
└──────────────────────────────────────────────────────────────┘
```

**关键原则：**
- 行为树只输出语义 `behavior_name`，不维护 `ACT_*` 动作序列
- 6 个正式情绪行为：`expressCalm / expressJoy / expressExcitement / expressAnxiety / expressFear / expressCuriosity`
- 具体 `ACT_*` 动作由 `marsdog_action_executor` 根据 `behavior_name + level + interaction_mode` 选择
- 公共接口定义在 `marsdog_interfaces`，不在本项目内重复定义

## 项目结构

```
marsdog_behavior/                   # ← 仓库根目录软链接到 ~/ros2_ws/src/marsdog_behavior
├── marsdog_behavior/               # ROS2 节点层（薄壳）
│   ├── __init__.py
│   ├── ros_node.py                 # 主 ROS2 节点（订阅/发布/Timer/AC）
│   ├── intent_mapper.py              # Event→Intent→Behavior 管道
│   ├── state_event_refiner.py       # 粗粒度事件 + 状态 → 细粒度 Intent
│   ├── candidate_pool.py           # 候选池（composite-key去重 + sub_priority排序）
│   ├── behavior_selector.py        # 优先级选择 + 抢占判断
│   ├── relevance_checker.py        # levelEvents 字符串比对
│   ├── interaction_resolver.py     # person presence → interaction_mode
│   ├── execution_manager.py        # goal 生命周期管理
│   ├── result_event_mapper.py      # → /behavior/result_event
│   ├── perception_client_adapter.py # 感知系统适配（audio白名单 + visual仅缓存）
│   ├── action_client_adapter.py    # Action Client → /execute_behavior
│   ├── ros2_compat.py              # ROS2/Standalone 兼容层
│   ├── interfaces.py               # Python 数据结构（BehaviorSignal 等）
│   ├── mock_action_executor_node.py # [待删除] 内置 Mock 执行器
│   ├── standalone_demo.py          # 无 ROS2 环境独立 Demo
│   └── tests/                      # ROS2 层测试
│
├── bionic_dog_bt/                  # 纯 Python 行为树框架（无 ROS2 依赖）
│   ├── behavior_tree_node.py       # 基类：Status, Node, Sequence, Selector
│   ├── blackboard.py               # 运行时共享状态
│   ├── actions.py                  # ExecuteActiveBehavior（抢占/超时/冷却）
│   ├── conditions.py               # ActiveLevelCondition + BehaviorRelevanceCondition
│   ├── decorators.py               # Inverter, CooldownDecorator
│   ├── tree_builder.py             # 构建 7 层优先级 Selector
│   ├── datatypes.py                # ActiveBehavior, EmotionState, NeedState, ...
│   ├── constants.py                # 优先级层级、状态、中断策略、映射表
│   ├── emotion_module.py           # 情绪状态追踪（6 种 × 衰减率）
│   ├── need_module.py              # 内部需求追踪（7 种 × 三级阈值）
│   ├── emotion_behavior_table.py   # 情绪→行为映射表（56 个候选）
│   ├── action_catalog.py           # [已弃用] 动作目录（仅 Mock 回退用）
│   ├── logger.py                   # 统一日志（结构化事件 + JSON）
│   ├── mock_input_provider.py      # Mock 上游注入
│   ├── mock_action_executor.py     # Mock 执行器
│   ├── mock_perception_client.py   # Mock 感知服务
│   ├── yaml_loader.py              # YAML 配置加载
│   └── demo.py                     # 交互式 CLI Demo
│
├── config/
│   ├── behaviors.yaml              # 行为配置（遗留兼容）
│   ├── behavior_categories.yaml    # 7层分类 + priority_level
│   ├── event_intent_map.yaml       # 事件 → category → intent 映射
│   ├── intent_action_pool.yaml     # intent → 候选 behavior_name 池（零 ACT_*）
│   ├── emotion_behavior_map.yaml   # 13个情绪事件 → 6个语义行为
│   └── legacy_behavior_aliases.yaml # 65个旧→新行为名兼容映射
├── launch/
│   └── behavior_tree.launch.py     # ROS2 Launch
├── tests/                          # 框架层测试（76 个）
├── package.xml                     # ROS2 ament_python 配置
├── setup.py                        # ROS2 入口
├── setup.cfg
├── pyproject.toml                  # uv 项目配置
└── README.md
```

## 行为树层级

| Lv | 名称 | 需求/事件 | 语义行为 |
|----|------|------|---------|
| 0 | 系统级 | Energy, 特殊生存避险 | `restInPlace`, `recharge`, `emergency_stop` |
| 1 | 外部交互 | 触觉/听觉/视觉/环境变化/语音指令 | `respond_owner_call` 等 |
| 2 | 生理紧急 | 排泄, 困倦 | `defecate`, `sleepNow` |
| 3 | 生理常规 | 饥渴, 清洁 | `eatNormally`, `eatExcitedly`, `cleanSelf` |
| 4 | 心理需求 | 社交, 探索 | `seekHumanInteraction`, `exploreRoom`, etc. |
| 5 | 情绪表达 | 6 类情绪 × 强度区间 | `expressCalm/Joy/Excitement/Anxiety/Fear/Curiosity` |
| 6 | 空闲 | 无活跃需求/情绪 | `idle_look_around`, `idle_rest` |

数值越小优先级越高。Root 是 `Selector(memory=False)`。Lv.1 内部 `sub_priority`：触觉(0) > 听觉(1) > 视觉(12) > 环境变化(20)。

## 快速开始

### 安装依赖

```bash
uv sync
```

### 纯 Python Demo（无需 ROS2）

```bash
uv run python -m bionic_dog_bt.demo
```

交互命令：`hunger 85`, `bladder 95`, `social 75`, `emotion Joy 90`, `cmd CMD_SIT`, `person on`, `auto 20`, `status`, `quit`

### ROS2 Standalone Demo（无需 ROS2）

```bash
uv run python -m marsdog_behavior.standalone_demo
```

### ROS2 部署

```bash
# 1. 软链接三个包到 ROS2 workspace（注意：行为树软链接指向仓库根目录，不是子目录）
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src

ln -s /path/to/marsdog_interfaces .
ln -s /home/cat/xbb/20260702_MarsDogTree marsdog_behavior
ln -s /path/to/marsdog_action_executor .

# 2. 一次性构建全部（marsdog_interfaces 必须先于其他包就绪）
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash

# 3. 启动动作执行器（先启动，行为树才能通过 ActionClient 对接）
ros2 run marsdog_action_executor action_executor_node &

# 4. 启动行为树节点
ros2 launch marsdog_behavior behavior_tree.launch.py
```

> **注意**：`marsdog_interfaces` 必须在 `marsdog_behavior` 之前构建。如果分开构建，需要在构建 interfaces 后 `source install/setup.bash`，再构建 behavior。一次性 `colcon build --symlink-install` 最简单。

> **回退**：如果 `marsdog_interfaces` 或 `marsdog_action_executor` 不可用，行为树节点会自动降级到内置 MockActionExecutor，并在日志中给出清晰提示。

## 事件 → Intent → Behavior 管道

行为树不再直接将感知事件映射为 `behavior_name`，改为四层管道：

```
前置事件 → category → intent → action_pool → selected behavior_name
```

### 行为树直接处理的事件（白名单）

| 来源 | 事件 | → intent 示例 |
|------|------|-------------|
| **audio_direct** | `EVT_VOICE_CALL_NAME` | `orient_to_sound` |
| **audio_direct** | `EVT_VOICE_COMMAND_KNOWN` + CMD_SIT | `command_sit` |
| **need** | `NEED_HUNGER_TRIGGERED` | `hunger_seek_food` |
| **emotion** | `EMO_JOY_HIGH` | `expressJoy` (Lv5, level=HIGH) |

### 行为树不直接处理的事件

| 来源 | 事件 | 理由 |
|------|------|------|
| audio | `EVT_VOICE_PRAISE / SCOLD / HAPPY / SAD / NEUTRAL` | → emotion_engine_node |
| visual | 全部 `EVT_VISION_*` | 仅用于 active_target 缓存，不生成候选 |

> 详见 [docs/event_intent_pipeline.md](docs/event_intent_pipeline.md) 和 [docs/behavior_tree_internals.md](docs/behavior_tree_internals.md)

## 核心机制

### 抢占规则

| 条件 | 结果 |
|------|------|
| `new.Lv < cur.Lv` + `immediate` | 立即抢占 |
| `new.Lv < cur.Lv` + `safe_point` | 等 `safe_to_interrupt=true` |
| `new.Lv < cur.Lv` + `non_interruptible` | 不抢占（emergency_stop 例外） |
| `new.Lv == cur.Lv` + `Δvalue >= 15` | 抢占 |
| `new.Lv == cur.Lv` + `Δvalue < 15` | 不抢占（防抖） |
| `new.Lv > cur.Lv` | 不抢占 |

### 情绪/需求相关性（字符串比对）

行为树**不做值判断**，只比对上游节点发布的事件字符串：

```
signal_event: event_type="EMO_JOY_HIGH"  → 候选入池 (trigger_event="EMO_JOY_HIGH")
state:        levelEvents["Joy"]="EMO_JOY_HIGH"  → 持续更新

执行时: levelEvents["Joy"] == trigger_event ?
  "EMO_JOY_HIGH" == "EMO_JOY_HIGH" → 仍在同一区间 → 执行
  "EMO_JOY_MID"  != "EMO_JOY_HIGH" → 情绪已衰减 → 跳过
```

需求同理：`levelEvents["Hunger"]` vs `trigger_event`。

语音指令类候选属于 `event_once`，只做 TTL 判断，不做 levelEvents 持续相关性判断。

### 日志系统

```bash
LOG_LEVEL=DEBUG uv run python -m marsdog_behavior.ros_node
LOG_FILE=/tmp/bt.log uv run python -m marsdog_behavior.ros_node
```

## 正式接口

### 订阅

| Topic | 类型 | QoS | 频率 |
|-------|------|-----|------|
| `/emotion/state` | String(JSON) | BEST_EFFORT | 1Hz |
| `/emotion/signal_event` | String(JSON) | RELIABLE | 事件驱动 |
| `/internal_need/state` | String(JSON) | BEST_EFFORT | 1Hz |
| `/internal_need/signal_event` | String(JSON) | RELIABLE | 事件驱动 |
| `/perception/audio_event` | String(JSON) | RELIABLE | 事件驱动 |
| `/perception/visual_event` | String(JSON) | BEST_EFFORT | 事件驱动 |

### 发布

| Topic | 类型 | 说明 |
|-------|------|------|
| `/behavior/result_event` | String(JSON) | 需求行为结果（STARTED/COMPLETED/FAILED/TIMEOUT/INTERRUPTED） |

### Action Client

| Action | 方向 | 说明 |
|--------|------|------|
| `/execute_behavior` | Client → Server | 下发 behavior_name 给动作执行器 |

### Service Client

| Service | 方向 | 说明 |
|---------|------|------|
| `/perception/perception_task` | Client → Server | check_person / detect_objects |

### 不是正式接口的 Topic

以下 Topic 是动作执行器或可视化工具的**调试接口**，不作为行为树项目的正式依赖：

- `/execute_behavior/goal` — debug
- `/execute_behavior/feedback` — debug
- `/execute_behavior/result` — debug

## 职责边界

### 行为树负责

1. 接收 `/emotion/signal_event`、`/internal_need/signal_event`、`/perception/audio_event`（白名单）→ 通过 intent 管道生成候选
2. 维护候选行为池（去重、TTL、来源记录）
3. 按优先级、抢占规则、冷却、超时、相关性（levelEvents 比对）选择行为
4. 执行前判断 interactive / solo
5. 通过 Action Client 向 `/execute_behavior` 下发 `behavior_name`
6. 接收执行器 feedback/result
7. 发布 `/behavior/result_event`
8. 缓存 `active_target`（仅用于 check_person，不生成行为候选）

### 行为树不负责

1. 直接消费 `EVT_VISION_*` 生成行为候选 → 视觉事件由 emotion_engine/internal_need 消费
2. 直接消费 `EVT_VOICE_PRAISE/SCOLD/...` 生成行为候选 → 音频情绪事件由 emotion_engine 消费
3. 具体动作序列编排 → 由 `marsdog_action_executor` 负责
4. `ACT_POSTURE_xxx` 等底层动作 ID 的正式维护 → 由 `marsdog_action_executor` 负责
5. 真实电机、舵机、云台、导航控制 → 由 `marsdog_action_executor` 负责
6. 重复定义 `ExecuteBehavior.action` → 由 `marsdog_interfaces` 负责
7. 暴露 `/execute_behavior/goal|feedback|result` 作为正式业务 topic

## 依赖包

| 包名 | 类型 | 说明 |
|------|------|------|
| `marsdog_interfaces` | ROS2 | 公共接口包（action/msg/srv 定义） |
| `marsdog_behavior` | ROS2 | 本项目（行为树决策引擎） |
| `marsdog_action_executor` | ROS2 | 独立下游项目（动作执行器） |

**构建前必须**先构建 `marsdog_interfaces`：

```bash
cd ~/ros2_ws
colcon build --packages-select marsdog_interfaces --symlink-install
source install/setup.bash
colcon build --packages-select marsdog_behavior marsdog_action_executor --symlink-install
```

如果 `marsdog_interfaces` 尚未创建，本项目会回退到内置 MockActionExecutor，并给出清晰日志提示。

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/ros2_nodes.md](docs/ros2_nodes.md) | **ROS2 节点说明**：所有节点、Topic、QoS、消息格式、调试命令 |
| [docs/behavior_tree_internals.md](docs/behavior_tree_internals.md) | 行为树内部逻辑：7层仲裁、抢占规则、相关性检查、执行流程 |
| [docs/behavior_semantic_map.md](docs/behavior_semantic_map.md) | **行为语义映射表**：需求/情绪事件→Intent→Behavior 完整映射 |
| [docs/event_behavior_table.md](docs/event_behavior_table.md) | **事件-行为对照表**：所有事件→Behavior 完整映射（从 YAML 自动生成） |
| [docs/event_intent_pipeline.md](docs/event_intent_pipeline.md) | 事件管道：白名单、映射链路、Goal/Result 示例 |
| [docs/visualization_interface.md](docs/visualization_interface.md) | 可视化接口：Topic 列表、JSON Schema、状态机、订阅代码模板 |
| [docs/action_executor_design.md](docs/action_executor_design.md) | 动作执行器设计方案（参考） |
| [marsdog_ros2/DOCUMENTATION.md](marsdog_ros2/DOCUMENTATION.md) | 旧版接口文档（已归档） |

## 测试

```bash
uv run pytest -q                        # 全部 113 个测试
uv run pytest tests/ -q                 # 76（框架层）
uv run pytest marsdog_behavior/tests/ -q # 37（ROS2 层 + e2e）
```
