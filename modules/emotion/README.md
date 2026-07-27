# Marsdog 需求与情绪计算节点

当前仓库这一层实现内部需求计算、情绪计算、ROS2 输入适配和状态/事件发布。

## 目录

- `marsdog_core/`：纯 Python 需求/情绪计算核心，不依赖 ROS2。
- `marsdog_ros2/`：ROS2 topic 适配和节点入口。
- `configs/`：需求阈值、情绪规则、性格预设。
- `tests/`：标准库 `unittest` 测试。
- `docs/`：接口和当前实现说明。

## 核心入口

```python
from marsdog_core import MarsdogNeedSystem, MarsdogEmotionSystem

need_system = MarsdogNeedSystem()
emotion_system = MarsdogEmotionSystem()
```

## 需求计算示例

```python
from marsdog_core import MarsdogNeedSystem

system = MarsdogNeedSystem()
system.SetDemandValue("Hunger", 80)

system.OnBehaviorResultEvent({
    "action_type": "ACTION_EAT",
    "result_type": "COMPLETED",
    "metadata": {
        "foodType": "NormalFood",
        "portions": 1,
        "eatEfficiency": "Full",
    },
})

print(system.GetDemandValue("Hunger"))          # 60
print(system.GetInternalNeedStateValue())       # 可发布到 /internal_need/state
```

## 情绪计算示例

```python
from marsdog_core import MarsdogEmotionSystem

system = MarsdogEmotionSystem()
system.ApplyEmotionEvent("EVT_VOICE_PRAISE", {"masterId": True})

print(system.GetEmotionValue("Joy"))            # 36
print(system.GetEmotionStateValue())            # 可发布到 /emotion/state
print(system.GetEmotionSignalEventsValue())     # 区间变化事件
```

## ROS2 Topic

输入：

- `/perception/audio_event`
- `/perception/visual_event`
- `/behavior/result_event`

输出：

- `/internal_need/state`
- `/internal_need/signal_event`
- `/emotion/state`
- `/emotion/signal_event`

运行节点：

```bash
ros2 run marsdog_need_emotion internal_need_node
ros2 run marsdog_need_emotion emotion_engine_node
```

## 测试

```bash
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

## 开发规则

- 本层只发布数值状态和阈值/区间信号。
- 新增需求或情绪规则时，先更新 `configs/`，再补测试。
- 对外接口继续使用项目约定的 CamelCase 命名。
