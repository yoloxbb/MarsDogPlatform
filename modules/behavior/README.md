# MarsDog Behavior — 仿生机器狗行为决策引擎

> 独立项目交接、上下游接口、延迟队列、跟随和充电流程见
> [docs/HANDOFF.md](docs/HANDOFF.md)。

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
│                         ← /perception/vision/task             │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ marsdog_behavior — 本项目（行为树决策引擎）                      │
│                                                              │
│  事件 → intent → behavior 管道：                                │
│    audio_direct: EVT_VOICE_CALL_NAME / EVT_VOICE_COMMAND_*     │
│    need V2:      NEED_*_TRIGGERED / URGENT / OVERFLOW          │
│    emotion V2:   EMO_*_TRIGGERED                               │
│                                                              │
│  候选池 → 行为选择 → BT tick (7层)                              │
│  情绪相关性：state.emotions.<name>.triggered + 视觉人/无人路由  │
│  需求相关性：state.demands.<name>.triggered                     │
│  Hunger/Social/Exploration：视觉 Service → 食物/目标/物品上下文 │
│  Action Client → /execute_behavior                            │
│  发布 → /behavior/result_event                                │
│                                                              │
│  visual_event: 缓存场景作为 Service 回退，不直接生成行为候选    │
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
│ marsdog_interfaces — 行为公共接口包（独立）                      │
│  action/ExecuteBehavior.action                                │
│ marsdog_vision_interaction — 视觉接口包（独立）                  │
│  srv/VisionTask.srv                                           │
└──────────────────────────────────────────────────────────────┘
```

**关键原则：**
- 行为树只输出语义 `behavior_name`，不维护 `ACT_*` 动作序列
- 情绪 V2 每种情绪只有一个阈值事件，并由视觉人/无人结果选择
  `*WithHuman` / `*Alone` 两个独立 Behavior；需求强度与视觉上下文共同确定
  `behavior_name`
- 具体 `ACT_*` 动作由 `marsdog_action_executor` 根据 `behavior_name + interaction_mode` 选择
- 行为接口定义在 `marsdog_interfaces`；视觉任务接口由
  `marsdog_vision_interaction` 提供，本项目不重复定义

## 项目结构

```
marsdog_behavior/                   # ← 仓库根目录软链接到 ~/ros2_ws/src/marsdog_behavior
├── marsdog_behavior/               # ROS2 节点层（薄壳）
│   ├── __init__.py
│   ├── ros_node.py                 # 主 ROS2 节点（订阅/发布/Timer/AC）
│   ├── runtime.py                  # 传输无关运行时（仲裁/BT tick/生命周期事件）
│   ├── intent_mapper.py              # Event→Intent→Behavior 管道
│   ├── candidate_pool.py           # 候选池（同名唯一占位/TTL/排序/冷却等待）
│   ├── config_paths.py             # 源码/ROS2 安装配置路径解析
│   ├── behavior_selector.py        # 旧调用方兼容门面
│   ├── relevance_checker.py        # 独立相关性检查兼容模块
│   ├── interaction_resolver.py     # 独立互动上下文兼容模块
│   ├── execution_manager.py        # 独立执行管理兼容模块
│   ├── result_event_mapper.py      # → /behavior/result_event
│   ├── perception_client_adapter.py # 感知适配（audio白名单 + 视觉服务/缓存）
│   ├── action_client_adapter.py    # Action Client → /execute_behavior
│   ├── ros2_compat.py              # ROS2/Standalone 兼容层
│   ├── interfaces.py               # Python 数据结构（BehaviorSignal 等）
│   ├── mock_action_executor_node.py # [待删除] 内置 Mock 执行器
│   ├── standalone_demo.py          # 无 ROS2 环境独立 Demo
│   └── tests/                      # ROS2 层测试
│
├── bionic_dog_bt/                  # 纯 Python 行为树框架（无 ROS2 依赖）
│   ├── behavior_tree_node.py       # 基类：Status, Node, Sequence, Selector
│   ├── arbitration.py              # 唯一抢占规则实现
│   ├── blackboard.py               # 运行时共享状态
│   ├── actions.py                  # ExecuteActiveBehavior（抢占/超时/冷却）
│   ├── conditions.py               # ActiveLevelCondition + BehaviorRelevanceCondition
│   ├── decorators.py               # Inverter, CooldownDecorator
│   ├── tree_builder.py             # 构建 7 层优先级 Selector
│   ├── datatypes.py                # ActiveBehavior, EmotionState, NeedState, ...
│   ├── constants.py                # 优先级层级、状态、中断策略、映射表
│   ├── emotion_module.py           # 情绪状态追踪（6 种 × 衰减率）
│   ├── need_module.py              # 内部需求 V2（7 种，含可选 URGENT）
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
│   ├── emotion_behavior_map.yaml   # 6个情绪 V2 事件 → 12个视觉分支行为
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
| 2 | 生理紧急 | 排泄, 困倦 | `barkShortAlert`, `sleepOnSide/sleepNow` |
| 3 | 生理常规 | 饥渴, 清洁 | `eatNormally/eatExcitedly`, `lickPaws` |
| 4 | 心理需求 | 社交, 探索 | 人/动物互动，熟悉/陌生物品探索 |
| 5 | 情绪表达 | 6 类情绪单阈值上升沿 | 有人 `*WithHuman` / 无人 `*Alone`，共 12 个 Behavior |
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

交互命令：`hunger 85`, `bladder 100`, `social 71`, `energy 91`,
`emotion Joy 90`, `event EVT_VOICE_COMMAND_SIT`, `person on`, `auto 20`,
`animal dog`, `object dog bowl`, `status`, `quit`

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

source install/setup.bash

# 3. 启动动作执行器（先启动，行为树才能通过 ActionClient 对接）
· ······· &

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
| **audio_direct** | `EVT_VOICE_CALL_NAME` | 开启会话级 `face_body_centering`（不创建动作候选） |
| **audio_direct** | `EVT_VOICE_COMMAND_SIT` | `command_sit` |
| **need** | `NEED_HUNGER_TRIGGERED` | `hunger_seek_food` |
| **emotion** | `EMO_JOY_TRIGGERED` | `expressJoyWithHuman` / `expressJoyAlone` (Lv5) |

语音强指令遵循一对一映射原则。当前 ROS2 运行时会拦截
`EVT_VOICE_CALL_NAME`，只开启会话级视角跟踪，不再下发会与后台控制争用底盘的
`respond_owner_call`；`IntentMapper` 中保留该映射仅供 standalone/兼容测试。
坐下、趴下、站立、等待、过来、跟随、握手、击掌、翻滚、转圈、返回、吐掉和
装死分别输出专用 Behavior。
`EVT_VOICE_COMMAND_STOP` 单独输出 Lv0 `emergency_stop`。

### 行为树不直接处理的事件

| 来源 | 事件 | 理由 |
|------|------|------|
| audio | `EVT_VOICE_PRAISE / SCOLD / HAPPY / SAD / NEUTRAL` | → emotion_engine_node |
| visual | 全部 `EVT_VISION_*` | 不直接生成候选；场景字段仅作为视觉服务回退 |

> 详见 [docs/event_behavior_table.md](docs/event_behavior_table.md) 和
> [docs/behavior_tree_architecture.md](docs/behavior_tree_architecture.md)。

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

### 情绪/需求相关性

情绪 V2 的 signal 只负责创建候选，state 的 `triggered` 布尔值负责持续相关性：

```
signal_event: event_type="EMO_JOY_TRIGGERED" → 视觉分流后生成 WithHuman/Alone 候选
state:        emotions["Joy"].triggered=true → 候选仍相关
state:        emotions["Joy"].triggered=false → 情绪已恢复，跳过候选
```

六类情绪 signal 都会先调用视觉 Service 的 `check_person`。有人时生成对应
`*WithHuman` Behavior，无人时生成 `*Alone` Behavior；等待
Service 期间发生恢复时，迟到的视觉结果不会创建候选。

内部需求同样只接受 schema 2.0。signal 的等级变化事件负责创建候选；
state 中每个需求的 `triggered` 是当前相关性的依据。Social 的
`URGENT/OVERFLOW` 也保持 `triggered=true`。state 或后续 signal 发生等级
变化时，会删除仍在队列中但事件等级已过期的旧候选。

Hunger 的 TRIGGERED/OVERFLOW 都会调用视觉服务识别狗粮：有狗粮分别选择
`eatNormally / eatExcitedly`，无狗粮分别选择 `seekFood /
seekFoodUrgently`。

Social 三个等级会调用视觉服务：有人则优先选择人类互动行为；无人时选择
猫/狗互动行为；无人且无猫狗时不创建行为候选。Exploration 会按熟悉物品、
陌生物品、空场景分流；熟悉物品进一步拆成玩耍物品、垃圾桶、快递盒、
纸巾、门和狗粮 6 个 Behavior。

V2 首次触发线使用 `triggerThreshold / triggerOperator`，可选中间紧急线
使用 `urgentThreshold / urgentOperator`。Bladder、Cleanliness、
Exploration 没有 `OVERFLOW`；Social 增加 `URGENT`。Energy 是电量缺口：
81 表示实际电量 19%，91 表示实际电量 9%。

语音指令类候选属于 `event_once`，只做 TTL 判断，不做状态持续相关性判断。

### 日志系统

```bash
LOG_LEVEL=DEBUG uv run python -m marsdog_behavior.ros_node
LOG_FILE=/tmp/bt.log uv run python -m marsdog_behavior.ros_node
```

## 正式接口

### 订阅

| Topic | 类型 | QoS | 频率 |
|-------|------|-----|------|
| `/emotion/state` | String(JSON), schema 2.0 | BEST_EFFORT | 1Hz |
| `/emotion/signal_event` | String(JSON), schema 2.0 | RELIABLE | 单阈值上升沿 |
| `/internal_need/state` | String(JSON), schema 2.0 | BEST_EFFORT | 1Hz |
| `/internal_need/signal_event` | String(JSON), schema 2.0 | RELIABLE | 等级变化 |
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
| `/perception/vision/task` | Client → Server | `VisionTask`：Emotion/Hunger/Social/Exploration 调用 `check_person / detect_objects` |
| `/perception/perception_task` | Client → Server | 旧 `PerceptionTask` 兼容回退 |

### 不是正式接口的 Topic

以下 Topic 是动作执行器或可视化工具的**调试接口**，不作为行为树项目的正式依赖：

- `/execute_behavior/goal` — debug
- `/execute_behavior/feedback` — debug
- `/execute_behavior/result` — debug

## 职责边界

### 行为树负责

1. 接收 `/emotion/signal_event`、`/internal_need/signal_event`、`/perception/audio_event`（白名单）→ 通过 intent 管道生成候选
2. 维护候选行为池（同名 queued/in-flight 唯一占位、TTL、来源记录）
3. 按优先级、抢占规则、冷却、超时和情绪/需求 `triggered` 相关性选择行为
4. 执行前判断 interactive / solo
5. 通过 Action Client 向 `/execute_behavior` 下发 `behavior_name`
6. 接收执行器 feedback/result
7. 发布 `/behavior/result_event`
8. 缓存 `humans / active_target / tracked_objects`，作为视觉服务不可用时的回退

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
| [docs/architecture.md](docs/architecture.md) | **当前架构**：上下游通信、运行时分层、时序、并发与异常路径 |
| [docs/ros2_nodes.md](docs/ros2_nodes.md) | **ROS2 节点说明**：所有节点、Topic、QoS、消息格式、调试命令 |
| [docs/event_behavior_table.md](docs/event_behavior_table.md) | **事件-行为对照表**：所有事件→Behavior 完整映射（从 YAML 自动生成） |
| [docs/behavior_tree_architecture.md](docs/behavior_tree_architecture.md) | 行为树内部逻辑：7层仲裁、抢占规则、相关性检查、执行流程 |
| [docs/HANDOFF.md](docs/HANDOFF.md) | 项目边界、上下游接口、队列、跟随、充电与交付验收 |

## 测试

```bash
uv run pytest -q
uv run pytest tests/ -q
uv run pytest marsdog_behavior/tests/ -q
```
