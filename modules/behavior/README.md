# Bionic Dog Behavior Tree

纯 Python 行为树框架，用于仿生机器狗应用层行为决策。

## 项目用途

为仿生机器狗提供优先级驱动的行为决策引擎。系统接收上游感知/情绪/需求模块的输入，通过行为树选择最合适的当前行为，发送到动作执行器执行，并处理行为抢占、冷却、超时等运行时逻辑。

## 行为树层级

| 层级 | 名称 | 数值 | 示例行为 |
|------|------|------|----------|
| Lv0 | 系统级 | 0 | emergency_stop, avoid_danger |
| Lv1 | 生理紧急 | 1 | excretion_request, sleep_request |
| Lv2 | 外部交互 | 2 | respond_owner_call, respond_touch_head |
| Lv3 | 生理常规 | 3 | seek_food_or_water, clean_self |
| Lv4 | 心理需求 | 4 | seek_social_interaction, explore_environment |
| Lv5 | 情绪表达 | 5 | express_happy, express_fear, express_curiosity |
| Lv6 | 空闲 | 6 | idle_look_around, idle_rest |

数值越小，优先级越高。行为树每次 tick 从 Lv0 开始重新检查（响应式 Selector，memory=False）。

## 核心模块说明

```
bionic_dog_bt/
├── datatypes.py          # 核心数据结构：ActiveBehavior, BehaviorSpec, BehaviorFeedbackEvent, ExecutorFeedback
├── constants.py          # 常量定义：优先级层级、状态、中断策略
├── behavior_tree_node.py # 行为树基类：Status, Node, Sequence, Selector
├── blackboard.py         # 黑板：运行时共享状态
├── yaml_loader.py        # YAML 配置加载器
├── mock_input_provider.py # Mock 上游输入：模拟感知/情绪/需求模块
├── mock_action_executor.py # Mock 动作执行器：模拟行为步骤执行
├── conditions.py         # 条件节点：ActiveLevelCondition
├── actions.py            # 动作节点：ExecuteActiveBehavior（含抢占逻辑）
├── decorators.py         # 装饰器节点：Inverter, CooldownDecorator
├── tree_builder.py       # 树构建器：组装完整行为树
└── demo.py               # 交互式演示

config/
└── behaviors.yaml        # 行为配置（优先级、超时、冷却、动作序列、风格）

tests/
├── test_behavior_tree.py    # 行为树基础、默认idle、层级抢占
├── test_preemption.py       # safe_point、non_interruptible 抢占策略
├── test_cooldown_timeout.py # 冷却、超时
└── test_executor.py         # 执行器反馈、行为完成
```

## 安装依赖

```bash
uv sync
```

## 运行 Demo

```bash
uv run python -m bionic_dog_bt.demo
```

交互命令：

| 命令 | 说明 |
|------|------|
| `owner_call` | 注入主人呼唤 |
| `touch_head` | 注入摸头 |
| `danger` | 注入危险 |
| `emergency` | 注入紧急停止 |
| `hunger` | 注入饥饿 |
| `clean` | 注入清洁需求 |
| `social` | 注入社交需求 |
| `happy` | 注入开心表达 |
| `fear` | 注入恐惧表达 |
| `curious` | 注入好奇表达 |
| `explore` | 注入探索需求 |
| `excretion` | 注入排泄需求 |
| `sleep` | 注入睡眠需求 |
| `idle` | 注入空闲 |
| `tick` | 手动推进一帧 |
| `auto` | 自动运行多帧 |
| `status` | 显示当前状态 |
| `quit` | 退出 |

## 运行测试

```bash
uv run pytest -q
```

## 后续替换为 ROS2

- `MockInputProvider` → 替换为 ROS2 Subscriber，接收感知/情绪/需求 topic
- `MockActionExecutor` → 替换为 ROS2 Action Client，发送真实动作指令
- `ActiveBehavior` → 可迁移为 ROS2 自定义 msg
- `BehaviorFeedbackEvent` → 可迁移为 ROS2 topic，发布行为结果
- `Blackboard` → 保持纯 Python，或映射到 ROS2 参数服务
