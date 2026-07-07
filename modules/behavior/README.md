# MarsDog Behavior Tree

仿生机器狗行为决策引擎。纯 Python 行为树框架 + ROS2 节点层。

## 架构

```
┌─────────────────────────────────────────────────────┐
│ 上游 ROS2 节点（独立运行）                            │
│                                                     │
│  emotion_engine_node    → /emotion/state (1Hz)       │
│                         → /emotion/signal_event      │
│  internal_need_node     → /internal_need/state (1Hz) │
│                         → /internal_need/signal_event │
│  perception_bridge      → /perception/audio_event    │
│                         ← /perception/perception_task │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ behavior_tree_node — 本项目的核心节点                  │
│                                                     │
│  订阅以上 5 个 topic → 候选池 → select() → BT tick    │
│  情绪/需求行为：字符串比对 levelEvents vs trigger_event │
│  语音指令：EVT_VOICE_COMMAND_KNOWN → command_id → 候选 │
│  执行时：check_person → interactive / solo           │
│  完成后：→ /behavior/result_event                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ /action_executor_node — 动作执行器                    │
│  Action Server: /execute_behavior                    │
│  随机从 action_catalog 选取动作序列，逐步推进          │
│  Goal → Feedback(progress/action) → Result           │
└─────────────────────────────────────────────────────┘
```

## 项目结构

```
├── bionic_dog_bt/               # 纯 Python 行为树框架
│   ├── behavior_tree_node.py    # 基类：Status, Node, Sequence, Selector
│   ├── blackboard.py            # 黑板：运行时共享状态
│   ├── actions.py               # ExecuteActiveBehavior（抢占/超时/冷却/反馈）
│   ├── conditions.py            # ActiveLevelCondition + BehaviorRelevanceCondition
│   ├── decorators.py            # Inverter, CooldownDecorator
│   ├── tree_builder.py          # 构建 7 层优先级 Selector
│   ├── datatypes.py             # ActiveBehavior, EmotionState, NeedState, ...
│   ├── constants.py             # 优先级层级、状态、中断策略、映射表
│   ├── emotion_module.py        # 情绪状态追踪（6 种情绪 × 衰减率）
│   ├── need_module.py           # 内部需求追踪（7 种需求 × 三级阈值）
│   ├── emotion_behavior_table.py # 情绪→行为映射表（56 个候选行为）
│   ├── action_catalog.py        # 动作目录（19 个行为，每阶段随机选动作）
│   ├── logger.py                # 统一日志系统（结构化事件 + JSON 输出）
│   ├── mock_input_provider.py   # Mock 上游注入（情绪/需求/语音/视觉）
│   ├── mock_action_executor.py  # Mock 执行器（从 action_catalog 随机选动作）
│   ├── mock_perception_client.py # Mock 感知服务（check_person / detect_objects）
│   ├── yaml_loader.py           # YAML 配置加载
│   └── demo.py                  # 交互式 CLI Demo
│
├── marsdog_ros2/                # ROS2 节点层
│   ├── behavior_tree_node.py    # /behavior_tree_node — 主节点
│   ├── mock_action_executor_node.py # /action_executor_node — Action Server
│   ├── perception_bridge.py     # 感知桥接（audio_event 订阅 + perception_task 调用）
│   ├── interfaces.py            # Python 版消息定义（BehaviorSignal / BehaviorFeedback / ExecuteBehavior*）
│   ├── ros2_compat.py           # ROS2 兼容层（无 ROS2 时降级为 mock Node）
│   ├── standalone_demo.py       # 无 ROS2 环境独立 Demo
│   ├── action/ExecuteBehavior.action  # ROS2 Action 定义
│   ├── msg/*.msg                # ROS2 消息定义
│   ├── launch/                  # ROS2 Launch
│   ├── tests/                   # ROS2 层测试
│   ├── package.xml / setup.py   # ROS2 ament_python 配置
│   └── DOCUMENTATION.md         # 接口文档
│
├── config/
│   └── behaviors.yaml           # 行为配置
│
└── tests/                       # 框架层测试（76 个）
```

## 行为树层级

| Lv | 名称 | 示例行为 |
|----|------|---------|
| 0 | 系统级 | emergency_stop, avoid_danger |
| 1 | 生理紧急 | excretion_request, sleep_request |
| 2 | 外部交互 | respond_owner_call, respond_touch_head |
| 3 | 生理常规 | seek_food_or_water, clean_self |
| 4 | 心理需求 | seek_social_interaction, explore_environment |
| 5 | 情绪表达 | 56 个候选行为（Joy/Excite/Fear/Anxiety/Curious/Calm × 强度区间 × 互动/非互动） |
| 6 | 空闲 | idle_look_around, idle_rest |

数值越小优先级越高。Root 是 `Selector(memory=False)`，每次 tick 从 Lv0 重新检查。

## 快速开始

### 安装

```bash
uv sync
```

### 纯 Python Demo

```bash
uv run python -m bionic_dog_bt.demo
```

交互命令：`hunger 85`, `bladder 95`, `social 75`, `emotion Joy 90`, `cmd CMD_SIT`, `person on`, `auto 20`, `status`, `quit`

### ROS2 Standalone Demo（无需 ROS2）

```bash
uv run python -m marsdog_ros2.standalone_demo
```

### ROS2 部署

```bash
# 1. 创建 workspace 软链接
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
ln -s /home/cat/xbb/20260702_MarsDogTree/marsdog_ros2 .
ln -s /home/cat/xbb/20260702_MarsDogTree/bionic_dog_bt .

# 2. 构建
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select marsdog_ros2 --symlink-install
source install/setup.bash

# 3. 启动
ros2 launch marsdog_ros2 behavior_tree.launch.py
```

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

### 情绪/需求相关性（状态比对）

行为树**不做值判断**，只比对上游节点发布的事件字符串：

```
signal_event: event_type="EMO_JOY_HIGH"  → 候选入池 params.trigger_event="EMO_JOY_HIGH"
state:        levelEvents["Joy"]="EMO_JOY_HIGH"  → 持续更新

执行时: levelEvents["Joy"] == trigger_event ?
  "EMO_JOY_HIGH" == "EMO_JOY_HIGH" → 仍在同一区间 → 执行
  "EMO_JOY_MID"  != "EMO_JOY_HIGH" → 情绪已衰减 → 跳过
```

需求同理：`levelEvents["Hunger"]` vs `trigger_event`。

### 日志系统

```bash
LOG_LEVEL=DEBUG uv run python -m marsdog_ros2.behavior_tree_node
LOG_FILE=/tmp/bt.log uv run python -m marsdog_ros2.behavior_tree_node
```

结构化事件：`behavior_start`, `behavior_complete`, `preempt`, `relevance_pass`, `relevance_fail`, ...

### 动作选择

每个行为有多个阶段，每阶段从候选池中 `random.choice()`：

```
seek_food_or_water 执行三次:
  run1: ACT_PAW_AT_BOWL → ACT_LICK_FOOD → ACT_PAUSE_AND_LOOK_AT_OWNER → ACT_LICK_LIPS_OR_NOSE
  run2: ACT_SNIFF_BOWL_EDGE → ACT_CHEW_OR_CARRY_FOOD → ACT_CHASE_ROLLING_FOOD → ACT_SNIFF_GROUND_FOR_CRUMBS
  run3: ACT_SIT_OR_LIE_BY_BOWL → ACT_SCRATCH_FOOD → ACT_BURP → ACT_WALK_AWAY_OR_LIE_DOWN
```

## Topic / Service / Action 一览

| 接口 | 类型 | 方向 | 说明 |
|------|------|------|------|
| `/emotion/state` | sub | ← upstream | 当前情绪值 + levelEvents |
| `/emotion/signal_event` | sub | ← upstream | 情绪区间变化 → 生成候选 |
| `/internal_need/state` | sub | ← upstream | 当前需求值 + levelEvents |
| `/internal_need/signal_event` | sub | ← upstream | 需求等级变化 → 生成候选 |
| `/perception/audio_event` | sub | ← upstream | EVT_VOICE_COMMAND_KNOWN → 语音候选 |
| `/perception/visual_event` | sub | ← upstream | active_target → 互动/非互动判断 |
| `/perception/perception_task` | service | ⇄ | check_person / detect_objects |
| `/behavior/result_event` | pub | → upstream | 行为完成反馈（COMPLETED/FAILED/...） |
| `/execute_behavior` | action | ⇄ | Goal → Feedback → Result |

## 测试

```bash
uv run pytest -q                        # 94 tests
uv run pytest tests/ -q                 # 76（框架层）
uv run pytest marsdog_ros2/tests/ -q    # 18（ROS2 层）
```
