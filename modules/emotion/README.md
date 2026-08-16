# Marsdog 需求、情绪与虚拟时间节点

当前仓库负责 Marsdog 的虚拟时间、内部需求、情绪、性格参数，以及 ONE1000
UWB 临时摸头输入。具体行为执行由外部行为模块负责，本项目通过
`/behavior/result_event` 接收执行结果并结算需求与情绪。

## 目录

- `marsdog_core/`：纯 Python 需求、情绪、性格、时间和 ONE1000 协议核心。
- `marsdog_ros2/`：ROS2 Topic 适配、节点和 launch 入口。
- `configs/`：需求阈值、情绪规则、性格预设。
- `tests/`：标准库 `unittest` 测试。
- `docs/`：接口和当前实现说明。

文档入口见 [文档导航](docs/README.md)。完整接口以
[ROS2 Topic 契约](docs/ros2_topic_contract.md) 和
[当前实现总结](docs/current_implementation_summary.md) 为准。

## 核心入口

```python
from marsdog_core import (
    MarsdogEmotionSystem,
    MarsdogNeedSystem,
    MarsdogPersonalitySystem,
    MarsdogTimeController,
)

need_system = MarsdogNeedSystem()
emotion_system = MarsdogEmotionSystem()
personality_system = MarsdogPersonalitySystem()
time_controller = MarsdogTimeController(timeScale=1)
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
print(system.GetEmotionSignalEventsValue())     # V2 阈值上升沿或 Calm 心跳事件
```

## ROS2 节点

构建并启动完整计算链路：

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=1
```

包内提供六个可执行节点：

- `time_controller_node`
- `midnight_test_node`
- `internal_need_node`
- `emotion_engine_node`
- `personality_node`
- `one1000_tactile_node`

`time_scale` 接受 `1-100` 整数。运行中只通过统一时间节点修改：

```bash
ros2 param set /time_controller_node time_scale 100
```

## 主要 ROS2 Topic

输入：

- `/perception/audio_event`
- `/perception/visual_event`
- `/perception/tactile_event`
- `/behavior/result_event`
- `/personality/state`
- `/simulation/time_state`

输出：

- `/simulation/time_state`
- `/internal_need/state`
- `/internal_need/signal_event`
- `/emotion/state`
- `/emotion/signal_event`
- `/personality/state`
- `/perception/tactile_event`
- `/one1000/status`

需求与情绪状态/事件使用 V2 JSON 协议，底层 ROS2 消息类型目前仍是
`std_msgs/msg/String`。行为模块对接方式见
[行为结果联调说明](docs/behavior_result_event_alignment.md)。

## ONE1000 临时摸头输入

默认距离模式在有效距离严格小于 10 cm 时立即发布摸头事件；持续保持在范围内
每 2 秒重复发布，离开后重新进入会立即再次发布。启用方式：

```bash
ros2 launch marsdog_need_emotion one1000_tactile.launch.py \
  serial_port:=/dev/serial/by-id/<实际设备路径> \
  detection_mode:=distance \
  distance_threshold_cm:=10.0 \
  touch_cooldown_seconds:=2.0
```

## 测试

```bash
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

## 开发规则

- 本层只发布数值状态和需求等级/情绪阈值信号。
- 新增需求或情绪规则时，先更新 `configs/`，再补测试。
- 修改情绪事件映射后运行 `python3 tools/export_emotion_event_catalog.py` 更新目录。
- 对外接口继续使用项目约定的 CamelCase 命名。
- 所有新增或修改函数添加中文简要注释，重点逻辑在函数内添加中文注释。
