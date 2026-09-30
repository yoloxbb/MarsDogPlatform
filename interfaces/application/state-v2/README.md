# Emotion / Needs state v2 兼容契约

/emotion/state、/emotion/signal_event、/internal_need/state、
/internal_need/signal_event 均使用 std_msgs/msg/String。
schema_version 沿用字符串 "2.0"；字段与领域权威由 Emotion/Needs 决定。

| 消息 | 原有职责 |
| --- | --- |
| emotion state | 情绪当前值、triggered 与恢复的权威快照 |
| emotion signal | 补足快照到来前的触发边沿，不代替快照恢复 |
| need state | demands 值、阈值、level/levelEvent 和活动标记 |
| need signal | 精确的需求等级变化；与快照的阈值、事件和等级一致 |
| timeContext | 原虚拟时间上下文；与原 wall timestamp 一同保留 |

BT 先验证完整需求快照，再应用其更新；数值不能用 bool 代替，值域 0..100，
阈值比较维持严格 gt。恢复、候选作废、视觉请求失效以及延续决策的顺序均保持。
情绪消费仍按自己的既有规则，不能因为需求快照有原子校验就宣称所有消息共用同一策略。
既有 Calm 心跳等行为在冻结结果中保留。

Emotion 内部共用 marsdog_ros2/common/state_publication.py 的发布机械逻辑：
时间选择、JSON 编码、消息工厂与 publish。状态计算不在公共发布层。
InternalNeedNode.PublishState 继续在状态后自动发布信号，并复用同一虚拟时间；
EmotionEngineNode 仍由原调用方显式安排信号发布。

`python3 -B tools/check_state_contracts.py` 调用真实发布方法和 BT 消费方法，
7 组生产序列、34 消费场景覆盖默认状态、等级进退、重复触发、恢复、声音到状态、
坏版本/数值/阈值/事件及混合非法快照。66c7eaa 前置基线只读。
时钟/随机种子固定，候选随机 ID/创建时刻及黑板 last_update 记账字段不比较；
权威值、标记、候选内容和待处理边沿均比较。此门禁没有 DDS 或设备。
Vision 对 emotion state 的既有消费路径未改动，沿用 Vision 单测及本机 smoke；
这 34 场景的消费者统计仅指 BT。
