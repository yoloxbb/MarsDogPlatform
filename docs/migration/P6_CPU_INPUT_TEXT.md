# P6 — 修复 CPU 意图输入差异（2026-09-29）

此前真实 Voice→ROS 验证发现：同一句“现在不要坐下。”在独立 Qwen 回放中为
NONE|SIT|STOP，而节点清理后传入“现在不要坐下”，输出变成 NONE|NONE|NONE。
本切片修复输入传递方式，未修改模型权重、v2 提示词、推理参数或分类规则。

## 根因与改动

原节点 _process_speech 先调用 _clean_text，删除标点、空格并规范中文数字；
它既用于词库、规则和事件文本，也曾直接交给新 Qwen CPU provider。
独立回放传入原文本，两条路径不一致。通用指令模型对格式有敏感性，
复现报告见 validation/cpu-input-text/baseline-pairs.json。

新增 provider 能力 preserve_asr_text，只有 IntentQwenCPUProvider 声明 true。
节点 _parse_intent 接收可选 raw_text，并逐 provider 选择输入：

| 使用者 | 输入 |
| --- | --- |
| Qwen CPU | 原始 ASR 文本；provider 原有首尾 strip 保留 |
| 原 RKLLM | 原 _clean_text 结果 |
| 规则回退 | 原 _clean_text 结果，即使上一步 CPU 失败 |
| 词库、KWS、目标解析和动作证据门限 | 原处理不变 |
| 对外 speech / 语义事件的 asr_text | 原清理结果，消息结构不变 |

CPU 主动拒绝仍停止规则回退；词库命中仍不调用模型。
没有共享可变的“上一条原文”，也没有用规则补出模型标签。
测试审计包装器透明传递该能力，并强制核对真实模型输入等于 ASR 原文。

## 修复前成对诊断

| 原文 | 原文预测 | 清理后预测 |
| --- | --- | --- |
| 现在不要坐下。 | NONE / SIT / STOP | NONE / NONE / NONE |
| 请在原地坐下。 | NONE / SIT / DO | NONE / SIT / DO |
| Do not follow me. | NONE / FOLLOW / STOP | NONE / FOLLOW / STOP |
| 你会坐下吗？ | NONE / SIT / STOP | NONE / SIT / STOP |

最后一条两种输入都没有正确得到 QUERY；它是保留的模型语义错误。
修复没有补句号、重写用户句子或根据关键词直接替换标签。
对于本来没有标点的 ASR 输入，模型仍可能误判，不能宣称已普遍解决否定理解。

## 验证范围

修复后的固定 CPU ROS 五场景通过：真实 WAV、Qwen 坐下、Qwen 否定、
注入拒绝、词库优先；会话与执行标志检查保持原断言。
全部原 40 条分类标注保持不变，另在首次运行前固定 12 条开发者编写的新措辞。
新增集合首次运行时未用于调提示词；随后仅用于下述未采用的布局实验。
它不是用户验收语料、产品准确率估计或持续未见过的留出集。
原模型质量问题与原冻结证据继续保留。

Voice 单元回归新增原文、标点/空格/数字、旧后端、规则回退、拒绝、词库优先和
对外文本一致性检查。最终结果及完整失败均见本阶段 release-manifest.json。
原七仓、RKLLM engine/provider/prompt、生产 YAML、依赖锁、ROS IDL 不变。

## 剩余限制

原有 Qwen v2 仍有泛化错误和明显 CPU 延时；本次是接线修复，不是微调或模型升级。
同步推理时的服务响应与中途取消仍未验收；不能从推理完成后的 stop 测试推断即时停止。
下一步应继续针对独立口令、无标点/否定/询问/转述进行质量验证，并验证推理期间的
会话控制，再扩大 BT/Action 真实感知联调。麦克风、设备、SLAM、远端 CI 限制仍保留。

## 本轮结果

| 门禁 | 结果 |
| --- | --- |
| Voice Humble 单元测试 | 424 passed，0 skip |
| 平台测试 | 36 passed |
| 公开契约 / 架构 | 25 passed / PASS |
| 独立 wheel / ROS build / 默认 smoke | PASS |
| 原七仓及兼容性保护 | PASS |
| CPU ROS 固定场景 | 5/5，12 次服务调用通过 |
| 原 40 条独立意图回放 | 21/40，与此前每条预测和失败完全一致 |
| 新增 12 条诊断 | 3/12；11 条限制执行输入没有可执行事件 |

新增集仅在“禁止站立”“禁止跟随”“后退”三条匹配预期。
原始标注和模型输出完整保留；没有因模型错误改写标签。
这说明保留原文修复了链路不一致，但 v2 提示词下模型泛化仍不足。

| 新增用例 | 期望 | 实际 |
| --- | --- | --- |
| no-lie | NONE / LIE / STOP | NONE / BARK / STOP |
| no-stand | NONE / STAND / STOP | NONE / STAND / STOP |
| no-follow | NONE / FOLLOW / STOP | NONE / FOLLOW / STOP |
| no-home | NONE / GO_HOME / STOP | SCOLD / NONE / NONE |
| ask-lie | NONE / LIE / QUERY | SCOLD / SIT / STOP |
| quote | NONE / NONE / NONE | SCOLD / SIT / DO |
| self-statement | NONE / NONE / NONE | NONE / STAY / DO |
| weather | NONE / NONE / NONE | NONE / DOG_STATUS / QUERY |
| praise | PRAISE / NONE / NONE | NONE / NONE / NONE |
| back | NONE / BACK / DO | NONE / BACK / DO |
| english-no-sit | NONE / SIT / STOP | NONE / NONE / NONE |
| english-capability | NONE / DOG_CAPABILITY / QUERY | NONE / NONE / NONE |

## 未采用的提示词布局实验

在 v2 回放之后，另起离线进程，将同样的规则和 37 条示例从多轮消息移到 system
说明，当前话语仍放 user 消息。仅在实验进程中替换 build_messages；未改正式提示词、
模型参数、权重、标签或事件门限。脚本、输出与哈希见 experiments/system-examples。

结果仍为 3/12；“请不要站起来。”与英文“Please do not sit down.”等被错分为 DO。
这些错误标签经现有门限后没有产生可执行事件；不能把“分类为 DO”写成“已执行动作”。
没有质量收益，且否定分类退化，因此不采用；正式版本仍为 qwen-cpu-intent-v2。
新增集的 description 保留首次运行前的说明；此后已经观察并用于该实验，不应再称独立留出集。
本实验仅是一次开发诊断，没有运行其 ROS 链路，也不构成任何模型验收。

## 复现与证据

在现有 WSL 环境、模型已准备的情况下：

~~~bash
python3 tools/marsdog.py voice-cpu-ros
python3 tools/marsdog.py intent-replay --manifest out/models/qwen2.5-0.5b-instruct/intent-replay.json
python3 tools/marsdog.py intent-replay --manifest validation/cpu-input-text/additional-manifest.json
~~~

后两个回放预期 exit 1，分别保留 21/40、3/12 的失败。新增清单中的绝对路径对应
当前 WSL 工作区；换机器须显式设置模型和用例路径，不能假定这些资产随 Git 分发。
本阶段 release-manifest.json 区分 software_acceptance、integration_acceptance、
fixture_quality_passed 与 model_acceptance；前面三项为 true，最后一项仍为 false。
历史 cpu-intent、cpu-voice-ros 证据未覆盖。
