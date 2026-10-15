# 触觉事件的两条消费路径

使用现有 `/perception/tactile_event`、`std_msgs/String`、schema_version `1.0`。
Emotion 的原订阅、规则与状态阈值保持原行为；BT 新增精确白名单消费入口。
传感器尚未到位，本次按用户授权预设以下映射，复用现有表达模板，不定义新的底盘报文或触觉驱动。

| event_type | BT 即时反应 | Emotion 现有基础增量 |
| --- | --- | --- |
| EVT_TACTILE_HEAD_PET | expressJoyAlone | Joy +25 / Calm +15 / Excite +5 |
| EVT_TACTILE_EAR_TOUCH | expressJoyAlone | Joy +20 / Calm +10 |
| EVT_TACTILE_NOSE_TOUCH | expressCuriosityAlone | Curious +10 / Calm +5 |
| EVT_TACTILE_BODY_STROKE | 无直驱映射 | Joy +20 / Calm +15 |

配置：`modules/behavior/config/tactile_events.yaml`。可整体关闭或逐事件修改。
新传感器适配器应发布 source、sensorType、touchState、Unix timestamp；本入口只接受 STARTED，
不使用长按重复包或 ENDED 产生新行为。TTL、时钟偏差、事件时间倒退、重复输入和单调时钟冷却均校验。

候选标记 `source=touch_direct`，统一进入 CandidatePool、仲裁、取消与 Action。
不伪装成内部情绪触发，不要求 Joy／Curious 已达到触发阈值。
同一事件仍可影响 Emotion；其后内部状态达到条件才生成内部候选。现有跨来源行为名去重和冷却继续生效。
硬件联调时固定 source／sensorType 与时间同步策略；软件模拟通过不表示已经采到真实触觉。

Emotion 按现有人格系数修正基础增量，默认 Curious 系数为 1.15，因此碰鼻的基础增量 10 修正并取整后为 12。
`cases.json` 同时约束 BT 反应和默认人格下的 Emotion 增量，由 `tools/check_approach_tactile_contracts.py`
在两个独立环境执行，不由 BT 导入 Emotion 实现。
