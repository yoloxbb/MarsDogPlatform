# Marsdog 行为系统

第一版项目采用 `Python + ROS2 通信适配`。核心行为引擎位于 `marsdog_core/`，保持纯 Python，不直接依赖 ROS2，便于单元测试和多人协作。

## 目录

- `marsdog_core/`：状态、需求、情绪、事件、仲裁、动作规划等核心逻辑。
- `marsdog_ros2/`：ROS2 节点适配层，把 Topic 输入转换为核心接口调用。
- `configs/`：需求阈值、情绪规则、优先级、动作序列配置。
- `tests/`：标准库 `unittest` 测试。
- `docs/`：API、优先级、命名规范文档。
  - `docs/behavior_tree_schema.md`：`ACTION_*` 内部行为树配置规范。

## 运行测试

```bash
python3 -m unittest discover -s tests
```

## 最小使用示例

```python
from marsdog_core import MarsdogBehaviorSystem

system = MarsdogBehaviorSystem()
system.SetDemandValue("Hunger", 80)
system.Tick()

print(system.GetCurrentAction())       # ACTION_EAT
print(system.GetConcreteActionQueue()) # ACT_* 具体动作序列
```

## 饥渴行为示例

```python
from marsdog_core import MarsdogBehaviorSystem

system = MarsdogBehaviorSystem()
system.InitializeMorningHunger()             # Hunger 随机进入 60-70
system.Tick(currentTime=8)                    # 白天每 10 分钟 Hunger += 1
system.ExecuteEat("普通粮", 1, "吃满时长")     # Hunger -= 20
```

ROS2 适配层中行为发布帧和需求增长 Tick 已分离：行为节点每 0.1 秒仲裁一次，但饥渴值每 600 秒才按时间规则增长一次。

## 全局需求规则

- `00:00-06:00` 所有需求锁定，不参与自然计算。
- 离开凌晨锁定期后，所有需求恢复晨起初始值。
- 内部需求发起的行为被高优先级事件打断时，关联需求值统一 `-20`，并执行 `ActionInterrupted` 情绪映射。
- 排泄行为被打断时使用专属规则：`Bladder -= 40`。
- 进食会增加排泄值：进食前 `Hunger > 90` 时 `Bladder += 25`，`Hunger > 70` 时 `Bladder += 20`。
- 行为落地输出使用 `GetCurrentActionSequence()` / `GetActionSequence(actionType)` 读取动作序列库。

## 行为树执行示例

`ACTION_EAT` 的正常进食流程会固定先执行 `ACT_RUN_TO_BOWL`，然后从准备、进食、互动、结束四个阶段中各随机抽取 1 个动作。
`ACTION_SLEEP` 会根据 `Sleepiness` 进入浅睡或深睡，并从准备入睡、睡眠中小动作、起床动作三个阶段中各随机抽取 1 个动作。

```python
from marsdog_core import MarsdogBehaviorSystem

system = MarsdogBehaviorSystem()
system.SetDemandValue("Hunger", 80)
system.Tick(currentTime=22)

while not system.IsCurrentBehaviorTreeFinished():
    status = system.TickCurrentBehaviorTree()
    current_action = system.GetCurrentConcreteAction()
    if current_action:
        print(current_action)
        system.MarkCurrentConcreteActionDone()
    if status == "SUCCESS":
        break
```

## 协作规则

- 新增需求、情绪、行为时，先更新 `configs/` 和枚举，再补测试。
- 核心逻辑不得直接依赖 ROS2；ROS2 只放在 `marsdog_ros2/`。
- 对外接口保留项目约定的 CamelCase 命名。
- 函数需要简要说明注释，复杂逻辑处添加必要行内注释。
