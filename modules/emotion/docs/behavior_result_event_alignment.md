# 行为结果 Topic 联调说明

本文面向行为执行模块，说明如何通过 `/behavior/result_event` 把动作结果回传给
Marsdog 需求与情绪节点。完整 Topic 列表与 QoS 以
[ROS2 Topic 契约](ros2_topic_contract.md) 为准。

## 1. 基本格式

- Topic：`/behavior/result_event`
- ROS2 类型：`std_msgs/msg/String`
- QoS：`RELIABLE, KEEP_LAST, depth=10`
- `data`：JSON 对象字符串

推荐每条消息完整填写以下字段：

```json
{
  "event_id": "result-000001",
  "timestamp": 1710000000.0,
  "action_type": "ACTION_EAT",
  "demand_type": "Hunger",
  "result_type": "COMPLETED",
  "metadata": {
    "foodType": "NormalFood",
    "portions": 1,
    "eatEfficiency": "Full"
  }
}
```

| 字段 | 发布方要求 | 当前消费兼容性 |
|---|---|---|
| `event_id` | 强烈建议填写非空 string | 缺省时仍处理，但无法去重 |
| `timestamp` | 建议填写 Unix 时间戳 | 当前只透传，不参与计算 |
| `action_type` | 必填 string | 未知或未登记 action 会被拒绝 |
| `demand_type` | 强烈建议填写 string | 可按 `action_type` 自动补全；显式填写非法值或不匹配值会被拒绝 |
| `result_type` | 必填 string | 只接受本文列出的六种结果 |
| `metadata` | 建议始终填写 object | 缺省或 `null` 按 `{}` 处理；其他类型会被拒绝 |

同一 `event_id` 在需求节点和情绪节点内都只处理一次。重试同一业务结果时必须
复用原 `event_id`；新的真实动作结果必须生成新 ID。

## 2. Action 与需求映射

| `action_type` | `demand_type` |
|---|---|
| `ACTION_EAT` | `Hunger` |
| `ACTION_DEFECATE` | `Bladder` |
| `ACTION_SLEEP` | `Sleepiness` |
| `ACTION_GROOM` | `Cleanliness` |
| `ACTION_RECHARGE` | `Energy` |
| `ACTION_PLAY_INVITE` | `Social` |
| `ACTION_SOCIAL_GREET` | `Social` |
| `ACTION_BOUNDARY_TEST` | `Social` |
| `ACTION_ATTENTION_SEEK` | `Social` |
| `ACTION_RESOURCE_SHARE` | `Social` |
| `ACTION_EXPLORE` | `Exploration` |
| `ACTION_SPACE_EXPLORE` | `Exploration` |
| `ACTION_OBJECT_EXPLORE` | `Exploration` |

只处理上表中的 action。显式 `demand_type` 必须与表中映射完全一致。

## 3. Result 语义

| `result_type` | 需求结算 | 情绪结算 |
|---|---|---|
| `STARTED` | 仅 `ACTION_SLEEP` 进入睡眠 | 不变 |
| `COMPLETED` | 按 action 完成规则结算 | `DemandSatisfied` |
| `FAILED` | 不变 | `DemandUnsatisfied` |
| `INTERRUPTED` | 对应需求按中断规则扣减 | `ActionInterrupted` |
| `CANCELLED` | 对应需求按中断规则扣减 | `ActionInterrupted` |
| `TIMEOUT` | 对应需求按中断规则扣减 | `DemandUnsatisfied` |

`ACTION_SLEEP` 的闭环从 `STARTED` 开始，不要等待睡眠完成后才回传。中断、取消
或超时时，如果当前正在睡眠，需求节点会先结束睡眠状态再结算中断扣减。

有效的 `COMPLETED` 成功结算后，如果对应需求仍停留在结算前的激活等级，需求
节点会复用当前 `NEED_*_TRIGGERED / URGENT / OVERFLOW` 事件名再次发布。消息
字段集合保持不变，`trigger=ACTION_RESULT_STILL_ACTIVE`，且
`previousLevel == level`。行为侧继续按原事件名处理即可。

如果结算导致等级变化，则只发布正常的 `trigger=LEVEL_CHANGED` 事件；降到
`NORMAL` 时发布 `NEED_*_RECOVERED`。当前只对 `COMPLETED` 启用同等级重发，
避免失败、中断或超时立即形成重试循环。

## 4. Metadata

### 4.1 进食

```json
{
  "foodType": "NormalFood",
  "portions": 1,
  "eatEfficiency": "Full"
}
```

- `foodType`：`PremiumFood / NormalFood / Snack`
- `portions`：数字
- `eatEfficiency`：`Full / HalfInterrupted`

### 4.2 充电

```json
{
  "energyValue": 88
}
```

`energyValue` 表示充电后的实际电量百分比，不是 Energy 需求值。内部会保存为
`Energy = 100 - energyValue`，因此示例最终得到 `Energy=12`。兼容字段名为
`energy_value` 和 `batteryValue`；未提供电量字段时默认充到目标电量 100%。

### 4.3 社交

```json
{
  "socialOutcome": "OwnerInteraction"
}
```

允许值：

- `OwnerInteraction`
- `DogHumanResponded`
- `DogAnimalResponded`
- `Rejected`
- `TimedOut`

### 4.4 探索

当前 `ACTION_EXPLORE* + COMPLETED` 统一令 `Exploration -= 15`，忽略
`metadata.discoveryType`。

## 5. 发布示例

进食完成：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"eat-001\",\"action_type\":\"ACTION_EAT\",\"demand_type\":\"Hunger\",\"result_type\":\"COMPLETED\",\"metadata\":{\"foodType\":\"NormalFood\",\"portions\":1,\"eatEfficiency\":\"Full\"}}'}"
```

开始睡眠：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"sleep-001\",\"action_type\":\"ACTION_SLEEP\",\"demand_type\":\"Sleepiness\",\"result_type\":\"STARTED\",\"metadata\":{}}'}"
```

充电到 88%：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"recharge-001\",\"action_type\":\"ACTION_RECHARGE\",\"demand_type\":\"Energy\",\"result_type\":\"COMPLETED\",\"metadata\":{\"energyValue\":88}}'}"
```

## 6. 联调验收

- [ ] 每个真实动作结果都有稳定且唯一的 `event_id`。
- [ ] `action_type` 与 `demand_type` 使用映射表中的精确值。
- [ ] 未知 action、非法 demand、映射不一致和非对象 metadata 不会改变状态。
- [ ] 重发同一 `event_id` 不会重复扣减或恢复需求。
- [ ] `COMPLETED` 后需求仍处于同一激活等级时，会收到当前等级事件的再次通知。
- [ ] `COMPLETED` 导致等级变化时只收到一条等级变化事件，不会重复通知。
- [ ] 收到睡眠需求后通过 `ACTION_SLEEP + STARTED` 进入睡眠。
- [ ] 充电 metadata 传实际电量百分比，而不是 Energy 缺口。
- [ ] 同时观察 `/internal_need/state` 与 `/emotion/state` 验证结算结果。
