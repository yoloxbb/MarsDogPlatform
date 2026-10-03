# 本地决策诊断 v1（历史）

本格式已由 [统一日志 v2](../../observability/README.md) 替代。下文只解释历史证据，
当前节点不再读取 MARSDOG_DECISION_TRACE_DIR，也不再写独立 decision trace。
当前行为观察使用 behavior.* 事件，录音报告从统一日志生成时间线。

这是可选的本地 JSONL 诊断，不是新的 ROS 消息或跨模块业务协议。
默认关闭；设置 `MARSDOG_DECISION_TRACE_DIR=/absolute/path` 后，
BT 进程向该目录的 `behavior-<pid>.jsonl` 追加记录。
不能据此修改授权、仲裁、取消或需求结算。写入失败只记一次警告，业务继续执行。
独立试用入口自动设置专用目录；普通运行不自动开启。

每条记录包含 schema_version=1、component=behavior、stage、pid、timestamp（Unix 秒）、
monotonic_ns（同一主机单调时钟纳秒）。身份字段按实际可用证据选填：
interaction_id、utterance_id、wake_id、event_type/trigger_event、command_id、intent、
source、behavior_name、candidate_id、behavior_id、goal_id。
数据字段包含 priority_level/value、reason、status/result，以及该阶段额外信息。

| stage | 观察点 |
| --- | --- |
| audio_received | BT 接收声音事件 |
| mapping_rejected | 映射或协议校验未产生候选；详细原始警告见节点日志 |
| candidate_created / candidate_queued | 生成候选 / 加入队列 |
| candidate_rejected | 需求门限、重复事件、旧会话、已有同名行为或缺少有效视觉目标 |
| candidate_waiting | 冷却、会话门限、等待旧 Goal 取消终态 |
| candidate_selected | 选出候选；ordering 保留原排序键 |
| arbitration | 原 evaluate_preemption 结果，含 allowed/reason 和当前 Goal |
| candidate_discarded / candidate_expired | 执行前树门限丢弃 / TTL 到期 |
| goal_dispatch / goal_accepted | 开始发送 / Action 接受，接受并不等于成功 |
| cancel_requested | 发起取消请求，尚未确认结束 |
| action_terminal / bt_terminal | Action 结果到达 / BT 处理终态 |

ordering 依次为原实现的 priority_level、semantic_rank、modality_rank、sub_priority/
behavior_rank、emotion_priority、负 value、负 created_at；该诊断不定义新的优先级规则。
等待/仲裁连续相同记录按候选合并，状态改变后再记录。缓存有界（4096 项）。
日志属于开发产物，按每次 run 目录管理；开启后会增加文件 I/O，不宣称实时性能不变。

`trial_report` 还将 Voice ASR 审计和 DDS 观察加入合并 trace.json：
component 为 voice/observer，stage 为 asr_started、asr_completed、voice_event_received。
这些是工具生成的报告条目，不回传运行节点；ASR duration 是预切分 WAV 的计算耗时。

以会话与语句身份选择初始记录，再以 candidate/goal 身份关联后续取消/终态。
终态记录可以没有 interaction_id；不能用相同 behavior_name 推断属于同一次执行。
诊断不是完整事件溯源：某些唤醒/会话分支仍主要依赖原节点日志，
进程退出、磁盘错误或禁用诊断都可能产生不完整时间线。

验收结果以真实 ASR 审计、DDS Goal/终态和子进程退出证据为准；
仅有一条日志或某个 PASS 文本不能证明动作成功。
参考 [录音试用](../../../docs/development/RECORDING_TRIAL.md) 与
[能力及功能开发](../../../docs/development/FEATURE_WORKFLOW.md)。
