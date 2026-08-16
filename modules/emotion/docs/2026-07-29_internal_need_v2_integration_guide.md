# 内部需求 V2 联调迁移说明

本文面向订阅 `/internal_need/state` 和 `/internal_need/signal_event` 的行为模块。
本次需求协议为破坏性升级，两个 Topic 的 `schema_version` 均由 `1.0` 改为
`2.0`；Topic 名、ROS2 消息类型 `std_msgs/msg/String` 和 JSON 外层传输方式不变。

## 1. 必须修改的内容

1. 接受 `schema_version == "2.0"`。
2. 首次触发线统一读取 `triggerThreshold / triggerOperator`。
3. 将 `urgentThreshold / urgentOperator` 解释为可选的中间紧急线；没有配置时
   两个字段均为 `null`。
4. `level` 枚举增加 `URGENT`，并处理 `NEED_SOCIAL_URGENT`。
5. 不再等待 Bladder、Cleanliness、Exploration 的 `OVERFLOW` 事件；这三个需求
   到 `100` 时仍是 `TRIGGERED`。

特别注意：V1 配置中的 `urgentThreshold / urgentOperator` 曾表示首次触发线。
V2 中该含义已迁移到 `triggerThreshold / triggerOperator`，旧解析方式会让除
Social 外的需求无法判断首次触发。

## 2. 新阈值和等级

所有比较符均为严格大于 `gt`。

| 需求 | NORMAL | TRIGGERED | URGENT | OVERFLOW |
|---|---|---|---|---|
| `Hunger` | `0-70` | `71-90` | 无 | `91-100` |
| `Bladder` | `0-75` | `76-100` | 无 | 无 |
| `Sleepiness` | `0-65` | `66-90` | 无 | `91-100` |
| `Cleanliness` | `0-70` | `71-100` | 无 | 无 |
| `Energy` | `0-80` | `81-90` | 无 | `91-100` |
| `Social` | `0-60` | `61-70` | `71-85` | `86-100` |
| `Exploration` | `0-60` | `61-100` | 无 | 无 |

Energy 仍是电量缺口：`Energy = 100 - 当前电量百分比`。因此 Energy `81`
表示当前电量 `19%`，首次触发；Energy `91` 表示当前电量 `9%`，进入满溢。
充电结果 metadata 中的 `energyValue / energy_value / batteryValue` 仍表示实际
电量百分比。

## 3. `/internal_need/state` V2

单个需求的完整字段：

```json
{
  "value": 71,
  "triggerThreshold": 70,
  "triggerOperator": "gt",
  "urgentThreshold": null,
  "urgentOperator": null,
  "overflowThreshold": 90,
  "triggered": true,
  "urgent": false,
  "overflow": false,
  "level": "TRIGGERED",
  "levelEvent": "NEED_HUNGER_TRIGGERED",
  "levelActive": true
}
```

Social 处于中间紧急等级时：

```json
{
  "value": 71,
  "triggerThreshold": 60,
  "triggerOperator": "gt",
  "urgentThreshold": 70,
  "urgentOperator": "gt",
  "overflowThreshold": 85,
  "triggered": true,
  "urgent": true,
  "overflow": false,
  "level": "URGENT",
  "levelEvent": "NEED_SOCIAL_URGENT",
  "levelActive": true
}
```

`triggered` 表示已经越过首次触发线；Social 在 `URGENT` 和 `OVERFLOW` 时也
保持 `triggered=true`。`urgent` 表示已经越过中间紧急线；未配置该线的需求
始终为 `false`。

## 4. `/internal_need/signal_event` V2

Social 从 `TRIGGERED` 进入 `URGENT` 的事件示例：

```json
{
  "schema_version": "2.0",
  "timestamp": 1710000000.0,
  "event_type": "NEED_SOCIAL_URGENT",
  "demand": "Social",
  "value": 71,
  "level": "URGENT",
  "previousLevel": "TRIGGERED",
  "triggerThreshold": 60,
  "triggerOperator": "gt",
  "urgentThreshold": 70,
  "urgentOperator": "gt",
  "overflowThreshold": 85,
  "overflowOperator": "gt",
  "trigger": "LEVEL_CHANGED"
}
```

ROS2 节点发布时还会统一附加完整的 `timeContext`，字段格式与
`/simulation/time_state.timeContext` 一致。

等级发生任何变化时仍发布“变化后的当前等级”事件。因此 Social 下降时的序列为：

```text
OVERFLOW -> URGENT     发布 NEED_SOCIAL_URGENT
URGENT -> TRIGGERED    发布 NEED_SOCIAL_TRIGGERED
TRIGGERED -> NORMAL    发布 NEED_SOCIAL_RECOVERED
```

行为组回传有效的 `COMPLETED` 后，需求节点会先结算对应需求。如果结算前后等级
相同且需求仍为 `TRIGGERED / URGENT / OVERFLOW`，系统会复用当前等级事件名再
发布一次，字段集合不变：

```json
{
  "event_type": "NEED_EXPLORATION_TRIGGERED",
  "demand": "Exploration",
  "value": 85,
  "level": "TRIGGERED",
  "previousLevel": "TRIGGERED",
  "trigger": "ACTION_RESULT_STILL_ACTIVE"
}
```

若结算导致等级变化，只发布原有 `LEVEL_CHANGED` 事件，不额外重发。降到
`NORMAL` 时发布 `RECOVERED`。`STARTED / FAILED / INTERRUPTED / CANCELLED /
TIMEOUT` 当前不会触发同等级重发，避免失败结果形成快速循环。

其他现有事件名 `NEED_<DEMAND>_TRIGGERED / OVERFLOW / RECOVERED` 保持不变，
但没有配置对应等级的需求不会产生该等级事件。

## 5. 行为侧推荐判断方式

行为是否进入候选集合，继续只判断首次触发状态：

```python
if demand_state["triggered"]:
    add_behavior_candidate(demand_name, demand_state["value"])
```

需要为 Social 提高调度优先级时，再单独使用 `level == "URGENT"` 或
`urgent == true`。不要用 `urgentThreshold is not null` 代替当前状态判断，
该字段只代表“配置了中间紧急线”。

紧迫度排序的需求侧实现没有变化：只比较 `triggered=true` 的需求，再按需求
原始值从高到低排序。

## 6. 可复现联调步骤

构建并启动：

```bash
cd /home/bird/Marsdog
colcon build --packages-select marsdog_need_emotion
source install/setup.bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=24 virtual_start_time:=06:00 random_seed:=12345
```

查看 V2 输出：

```bash
ros2 topic echo /internal_need/state --field data --full-length
ros2 topic echo /internal_need/signal_event --field data --full-length
```

建议行为侧至少回归以下事件序列：

```text
Social: 60 -> 61 -> 70 -> 71 -> 85 -> 86
event:  无 -> TRIGGERED -> 无 -> URGENT -> 无 -> OVERFLOW
```

同时确认 Bladder、Cleanliness、Exploration 到 `100` 后仍按
`NEED_<DEMAND>_TRIGGERED` 处理，不等待不存在的满溢事件。
