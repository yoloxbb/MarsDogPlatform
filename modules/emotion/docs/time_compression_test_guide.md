# Marsdog 三档时间压缩测试移交说明

本文档用于在较短真实时间内验收一个完整虚拟 24 小时的内部需求和情绪变化。

## 1. 时间模式

| `time_mode` | 倍率 | 虚拟 24 小时所需真实时间 | 需求 Tick | 情绪更新 |
|---|---:|---:|---:|---:|
| `standard_24h` | 1 | 24 小时 | 每 600 秒 | 1 Hz |
| `demo_12h` | 2 | 12 小时 | 每 300 秒 | 2 Hz |
| `demo_2h` | 12 | 2 小时 | 每 50 秒 | 12 Hz |

时间倍率只影响需求自然更新、睡眠恢复和情绪自然衰减。感知事件与
`/behavior/result_event` 仍在真实收到消息时立即处理，不会自动生成或压缩。

## 2. 启动

构建并加载环境：

```bash
cd /home/yahboom/Marsdog
colcon build --packages-select marsdog_behavior
source install/setup.bash
```

标准模式：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py \
  time_mode:=standard_24h
```

12 小时模式：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py \
  time_mode:=demo_12h
```

2 小时模式，推荐用于交付验收：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py \
  time_mode:=demo_2h \
  virtual_start_time:=06:00 \
  random_seed:=12345
```

参数说明：

| 参数 | 允许值 | 说明 |
|---|---|---|
| `time_mode` | 三种固定模式 | 初始值由 launch 设置；运行中通过时间控制节点修改 |
| `virtual_start_time` | `auto` 或 `HH:MM` | 压缩模式 `auto` 从当天 06:00 开始 |
| `random_seed` | `-1` 或非负整数 | `-1` 随机；固定值可重复 |

非法模式、非法时间和小于 `-1` 的种子会拒绝启动。完整一天验收必须从
`06:00` 开始；任意其他起点不会回放此前时段。

### 2.1 运行中切换倍率

节点运行期间可执行：

```bash
ros2 param set /time_controller_node time_mode demo_12h
ros2 param set /time_controller_node time_mode demo_2h
ros2 param set /time_controller_node time_mode standard_24h
```

切换只改变后续虚拟时间速度，不修改 `virtualDateTime`、需求值、情绪值、睡眠
状态或下一次需求 Tick。重复设置当前模式不会增加 `revision`。

## 3. 观察 Topic

另开终端并加载同一环境：

```bash
source /home/yahboom/Marsdog/install/setup.bash
ros2 topic echo /internal_need/state --field data --full-length
ros2 topic echo /internal_need/signal_event --field data --full-length
ros2 topic echo /emotion/state --field data --full-length
ros2 topic echo /emotion/signal_event --field data --full-length
ros2 topic echo /simulation/time_state --field data --full-length
```

四类消息均包含：

```json
"timeContext": {
  "mode": "demo_2h",
  "scale": 12,
  "revision": 1,
  "virtualStartDateTime": "2026-07-16T06:00:00+08:00",
  "virtualDateTime": "2026-07-16T14:30:00+08:00",
  "virtualTimestamp": 1784183400.0,
  "virtualElapsedSeconds": 30600.0,
  "wallTimestamp": 1784157900.0
}
```

顶层 `timestamp` 和 `wallTimestamp` 是真实 Unix 时间。需求昼夜规则应对照
`virtualDateTime`，不能使用真实系统时钟判断。

## 4. 行为结果注入

时间压缩不会自动模拟行为结果。测试需求闭环时，通过现有 Topic 注入对应结果。

进食完成：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"qa-eat-001\",\"action_type\":\"ACTION_EAT\",\"demand_type\":\"Hunger\",\"result_type\":\"COMPLETED\",\"metadata\":{\"foodType\":\"NormalFood\",\"portions\":1,\"eatEfficiency\":\"Full\"}}'}"
```

开始睡眠：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"qa-sleep-001\",\"action_type\":\"ACTION_SLEEP\",\"demand_type\":\"Sleepiness\",\"result_type\":\"STARTED\",\"metadata\":{}}'}"
```

每条测试消息必须使用新的 `event_id`，否则会被去重。完整睡眠轨迹需要在每次
出现 `NEED_SLEEPINESS_TRIGGERED` 后注入一次新的 `ACTION_SLEEP + STARTED`。

## 5. 完整一天结束条件

节点不会自动退出。满足任一条件即可认为完成一个虚拟日：

- `timeContext.virtualElapsedSeconds >= 86400`；
- 从虚拟 06:00 启动后，`virtualDateTime` 到达次日 06:00。

## 6. 验收表

| 检查项 | 通过标准 |
|---|---|
| 模式 | 四类消息的 `mode/scale` 与启动参数一致 |
| 动态切换 | `revision` 递增，虚拟时间连续，需求/情绪/睡眠状态不重置 |
| 起点 | 固定为虚拟 06:00，晨起需求已初始化 |
| 需求 Tick | 1/2/12 倍模式分别每 600/300/50 真实秒更新 |
| Tick 补算 | 节点短暂延迟后数值不丢增长 Tick |
| 情绪衰减 | 每虚拟秒衰减，区间事件顺序完整 |
| 需求事件 | `state.levelEvents[demand]` 与 signal 的 `event_type` 一致 |
| 情绪事件 | `state.levelEvents[emotion]` 与 signal 的 `event_type` 一致 |
| 睡眠 | 即时响应睡眠信号时，约清醒 6 小时 40-50 分，约 5 次睡眠会话 |
| 一天结束 | `virtualElapsedSeconds >= 86400` |
| 可重复性 | 相同 `random_seed` 和相同输入事件得到相同数值轨迹 |

## 7. 自动化回归

```bash
cd /home/yahboom/Marsdog
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

单元测试覆盖三档时间换算、参数校验、遗漏 Tick 补算、三模式需求/情绪轨迹
一致性，以及当前全天睡眠目标。
