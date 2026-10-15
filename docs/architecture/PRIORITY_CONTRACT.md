# 主等级与子优先级

`priority_level=2, sub_priority=1` 可显示为 `2.1`；存储和比较使用两个非负整数，禁止把 `2.1` 存为浮点优先级。
`2.10` 表示子级 10，因此在子级 2 之后，不与 `2.1` 混同。

兼容现有仲裁顺序：主等级 → semantic_rank → modality_rank → 子优先级 → emotion_priority → 强度降序 → 创建时间降序。
数字越小越优先，强度和时间维度除外。为了保留已有语义／模态优先关系，子级只在前三项相同时决定先后；
它不是绕过主等级、明确口令等规则的新总优先级。旧 `params.behavior_rank` 别名仍优先于 sub_priority。

候选池、兼容 Selector 和 BehaviorCandidate 共用 `bionic_dog_bt.arbitration` 的排序函数。
浮点、负数、布尔值、NaN 等无效等级在入池前拒绝；全部候选冷却时返回空，不再选中冷却中的第一项。

抢占继续依赖当前行为的 interrupt_policy、安全中断反馈、原有强度迟滞与会话例外。
更高子级优先权不代表可以越过 safe_point，也不能在 Cancel ACK 后立刻启动替代动作。
必须等真实终态释放占用；未知终态进入恢复流程。

例：三个候选都是 level=2、semantic_rank=3、modality_rank=3，子级 1、2、10，则依次为 2.1、2.2、2.10。
传感器来源与优先级独立：视觉、听觉、触觉的直驱候选和内部情绪／需求候选都使用同一规则。
