# Marsdog 1-100 整数倍率时间压缩测试移交说明

本文档用于在较短真实时间内验收一个完整虚拟 24 小时的内部需求和情绪变化。

## 1. 时间倍率

未启用凌晨特殊加速时，`time_scale` 接受 `1-100` 的整数。完整虚拟24小时所需真实时间为
`24 / time_scale` 小时，需求 Tick 真实周期为 `600 / time_scale` 秒，
情绪状态发布真实频率为 `time_scale` Hz；情绪自然衰减固定为真实时间 1 Hz。

| 倍率 | 虚拟 24 小时所需真实时间 | 需求 Tick | 情绪状态发布 | 情绪衰减 |
|---:|---:|---:|---:|---:|
| 1 | 24 小时 | 每 600 秒 | 1 Hz | 真实时间 1 Hz |
| 7 | 约 3 小时 25 分 43 秒 | 约每 85.71 秒 | 7 Hz | 真实时间 1 Hz |
| 12 | 2 小时 | 每 50 秒 | 12 Hz | 真实时间 1 Hz |
| 24 | 1 小时 | 每 25 秒 | 24 Hz | 真实时间 1 Hz |
| 100 | 14 分 24 秒 | 每 6 秒 | 100 Hz | 真实时间 1 Hz |

时间倍率只影响需求自然更新、睡眠恢复和情绪状态发布时间线，不影响情绪自然
衰减。感知事件与
`/behavior/result_event` 仍在真实收到消息时立即处理，不会自动生成或压缩。

## 2. 启动

构建并加载环境：

```bash
cd /home/bird/Marsdog
colcon build --packages-select marsdog_need_emotion
source install/setup.bash
```

1 倍模式：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=1
```

7 倍模式：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=7
```

100 倍模式，推荐用于快速交付验收：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 \
  virtual_start_time:=06:00 \
  random_seed:=12345
```

参数说明：

| 参数 | 允许值 | 说明 |
|---|---|---|
| `time_scale` | `1-100` 整数 | 初始值由 launch 设置；运行中通过时间控制节点修改 |
| `virtual_start_time` | `auto` 或 `HH:MM` | 1 倍 `auto` 从当前时间开始；2-100 倍从当天 06:00 开始 |
| `random_seed` | `-1` 或非负整数 | `-1` 随机；固定值可重复 |
| `midnight_acceleration_enabled` | `true/false` | 任意1-100倍率；每天00:00-06:00是否使用离散加速 |
| `midnight_duration_seconds` | 正数 | 每次虚拟凌晨六小时使用的真实秒数，默认30 |

非法倍率、非法时间和小于 `-1` 的种子会拒绝启动。完整一天验收必须从
`06:00` 开始；任意其他起点不会回放此前时段。

### 2.1 任意基础倍率联调中的每日凌晨30秒加速

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 \
  virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

时间流程：

```text
当天 00:00 → 用30秒到06:00
当天 06:00 → 恢复所选基础倍率
次日 00:00 → 再次用30秒到06:00
```

外部行为模块收到 `NEED_SLEEPINESS_TRIGGERED` 后应发布：

```json
{
  "event_id": "sleep-start-001",
  "action_type": "ACTION_SLEEP",
  "demand_type": "Sleepiness",
  "result_type": "STARTED",
  "metadata": {}
}
```

该模式不会在06:00退出。基础倍率为 `S` 时，一个完整虚拟日的真实耗时为：

```text
30秒 + 64800/S 秒
```

例如基础倍率100时约为 `11分18秒`。加速期间
`timeContext.scale=100`、`effectiveScale=720`、
`midnightAcceleration.active=true`；06:00后 `effectiveScale=100`、
`active=false`。把 `time_scale` 换成任意 `1-100` 整数均可使用；加速期间
动态切换倍率时，06:00后恢复新倍率。

电池使用独立的凌晨计时口径：这36个虚拟10分钟步骤只把实际经过的30秒按
1倍计入耗电，不会把6个虚拟小时全部计入。两小时满电续航下，单个30秒窗口
只消耗约 `0.4167%`；当前对外电量是整数，因此首次窗口结束通常仍显示100%，
但内部会保留小数余量。

### 2.2 独立30秒凌晨场景

只测试虚拟 `00:00-06:00` 的需求锁定、睡眠恢复和晨起重置：

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 \
  completion_hold_seconds:=2 \
  auto_start_sleep:=true \
  random_seed:=12345
```

测试时间源会执行36个虚拟10分钟步骤，每步约使用 `0.833` 秒真实时间。首次
出现 `NEED_SLEEPINESS_TRIGGERED` 时自动发布 `ACTION_SLEEP + STARTED`。
虚拟时间到达 `06:00` 后：

- 检查是否成功发送睡眠开始结果；
- 检查过程中是否实际进入过睡眠；
- 检查晨起重置后是否已经醒来；
- 输出 `Midnight test PASSED/FAILED`；
- 等待 `completion_hold_seconds` 后自动退出整个 launch。

该场景使用测试专用 `TIME_TEST_STEP`，不修改生产 `time_scale=1-100` 限制，
也不会让情绪节点回放21600条中间状态。情绪自然衰减只按实际经过的30秒计算。

### 2.3 运行中切换倍率

节点运行期间可执行：

```bash
ros2 param set /time_controller_node time_scale 7
ros2 param set /time_controller_node time_scale 24
ros2 param set /time_controller_node time_scale 100
ros2 param set /time_controller_node time_scale 1
```

切换只改变后续虚拟时间速度，不修改 `virtualDateTime`、需求值、情绪值、睡眠
状态或下一次需求 Tick。重复设置当前模式不会增加 `revision`。

## 3. 观察 Topic

另开终端并加载同一环境：

```bash
source /home/bird/Marsdog/install/setup.bash
ros2 topic echo /internal_need/state --field data --full-length
ros2 topic echo /internal_need/signal_event --field data --full-length
ros2 topic echo /emotion/state --field data --full-length
ros2 topic echo /emotion/signal_event --field data --full-length
ros2 topic echo /simulation/time_state --field data --full-length
ros2 topic echo /simulation/midnight_test_result --field data --full-length
```

四类消息均包含：

```json
"timeContext": {
  "mode": "custom",
  "scale": 7,
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
| 倍率 | 四类消息的 `scale` 与启动参数一致；`mode` 仅为兼容显示字段 |
| 动态切换 | `revision` 递增，虚拟时间连续，需求/情绪/睡眠状态不重置 |
| 起点 | 固定为虚拟 06:00，晨起需求已初始化 |
| Energy | 普通时段按倍率耗电；凌晨30秒特殊加速只按1倍累计30秒；06:00不重置电量 |
| 需求 Tick | 真实周期符合 `600 / time_scale` 秒 |
| Tick 补算 | 节点短暂延迟后数值不丢增长 Tick |
| 情绪衰减 | 倍率 `1/7/24/100` 下轨迹一致；`Anxiety/Calm` 数值保持不变，普通情绪降到阈值以下不发恢复事件 |
| 需求协议 | state/signal 均为 V2；仅 Social 具有 `URGENT`，事件名为 `NEED_SOCIAL_URGENT` |
| 需求边界 | Social 按 `60/61/70/71/85/86` 切换等级；Bladder/Cleanliness/Exploration 到100仍为 `TRIGGERED` |
| 需求事件 | `state.levelEvents[demand]` 与 signal 的 `event_type` 一致；紧迫度只比较已触发需求 |
| 情绪事件 | 普通情绪只发上升沿；无其他触发情绪时 Calm 按真实时间 1 Hz 持续发布，且不受倍率影响 |
| 睡眠 | 即时响应睡眠信号时，约清醒 6 小时 40-50 分，约 5 次睡眠会话 |
| 一天结束 | `virtualElapsedSeconds >= 86400` |
| 可重复性 | 相同 `random_seed` 和相同输入事件得到相同数值轨迹 |

## 7. 自动化回归

```bash
cd /home/bird/Marsdog
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

单元测试覆盖 `1-100` 倍率换算、参数校验、遗漏 Tick 补算、不同倍率需求/情绪轨迹
一致性，以及当前全天睡眠目标。
