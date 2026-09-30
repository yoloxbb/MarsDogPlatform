# /perception/audio_event v2：现有兼容契约

此目录集中记录当前跨模块事实和冻结样例，不引入协议升级或公共运行时依赖。
ROS 身份仍是 `std_msgs/msg/String`，内容为 JSON；端点、发布/订阅方向以
[接口登记](../../registry.json) 为准。Voice 生产，BehaviorTree 与 Emotion/Needs 消费。

## 字段与职责

| 字段组 | 现有含义 |
| --- | --- |
| schema_version、event_type | Voice 输出整数 2 和事件名；BT 要求精确整数 2（不接受 bool/float/string） |
| header.stamp、header.frame_id | 时间戳和角度坐标系；硬件唤醒角度使用 microphone_array |
| interaction_id、utterance_id、wake_id | Voice 分配关联 ID；BT 按事件类型检查归属和去重 |
| wake_angle、wake_confidence、wake_score_raw | 唤醒观测；Voice 将非有限值归零并夹紧置信度 |
| speaker_id / role / status / reason / confidence | 声纹观测；BT 检查当前 wake_id、会话和已有身份组合 |
| social、intent、emotion、action、control | 已有语义分类；它们本身不授予命令执行权限 |
| command_id、specific_event_type、dispatch_role、should_trigger_behavior_tree、slots | BT 的精确路由、权限和槽位校验输入 |
| is_executable | Voice 的分类输出；不同消费路径使用方式不同，不能单独当作通用授权器 |
| state、previous_state、state_reason | Voice 生命周期事件；匹配当前会话的 idle 才关闭会话 |
| 其余字段 | 文本、来源、响应、危险观测、时延等；完整输出字段及归一化默认值由 baseline.json 的 voice.empty 固定（时钟为 1000s） |

生产方实现：`modules/voice/marsdog_voice_interaction/messages/audio_event.py`。
命令词库与分类路由仍由 Voice 维护，BT 的路由表、需要门限和候选行为选择仍由 BT 维护，
Emotion/Needs 的事件映射、状态计算和需求结算仍由 Emotion 维护。

## 必须保留的兼容差异

- Voice 只输出已知字段；槽位过滤非 dict 元素并将 key/value 转为字符串。
  常规字段沿用 Python 类型转换，因此字符串 `"false"` 转 bool 仍为 true；
  本轮只记录，不修正此历史行为。
- BT 的命令入口要求明确的触发标志、dispatch_role、command_id、specific_event_type、
  interaction_id 和 utterance_id；已知槽位值冲突时拒绝，完全相同的重复槽位可接受。
  普通命令路径当前没有单独强制 is_executable；social_reaction 则要求其精确为 false。
- COMMAND_KNOWN 等摘要事件优先按非树事件处理，伪造触发标志也不会变成树命令。
  硬件 WAKEUP、模型 CALL、词库昵称事件保持不同身份和生命周期。
- BT 先校验、再修改会话；重复事件不重复生成候选，旧会话命令不能占用新会话。
  唤醒数值与坐标系校验、声纹关联、hold/release 和 idle 时序保持不变。
- Emotion/Needs 接受已有 JSON object / String 包装，不统一强制 schema v2。
  Emotion 按同名事件的既有时间窗口去重，Needs 按自身规则处理 owner presence；
  不把 BT 的授权拒绝自动解释成 Emotion 的拒绝。
- 不统一各模块日志、错误返回、空值/缺字段容错或业务去重策略。跨模块抽取前，
  先证明输入、输出、异常、副作用顺序都相同。

## 自动验证

`cases.json` 定义 10 组真实 Voice 生产输入和 46 个消费场景。
`baseline.json` 在 3f50614721419befddc4c59b218571ea95a5ddb1 的运行时源码上、
提取 BT 校验函数之前采集，并审查了权限、候选、会话和状态变化。

在三个模块各自的环境准备好后运行：

~~~bash
python3 tools/check_audio_contracts.py
~~~

工具不导入任何领域模块；worker 分别使用 Voice、BT、Emotion 的解释器和源码，
核对实际导入来源、环境路径及禁止的跨模块 import。两个消费者收到同一组 JSON 字节。
Voice 使用真实 codec、词库和分类路由；BT 使用真实感知解析和节点回调，在候选进入执行池
之前截获；Emotion 使用真实感知适配器、EmotionSystem 与 NeedSystem。
固定时钟/随机种子，候选只去掉随机 candidate_id 和 created_at；保留所有候选参数及会话快照。

这是无 ROS 传输、无模型推理、无动作执行的兼容性测试，不能代表硬件、DDS、ASR 精度、
完整 Voice 会话或 Action 取消验收。对应既有模块测试和 ROS smoke 仍须单独执行。
工具不会更新基线；更改基线需要独立说明语义变化并共同评审，不能用重生成掩盖回归。
