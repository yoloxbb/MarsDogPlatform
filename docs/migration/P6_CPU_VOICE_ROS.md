# P6 — 真实 CPU Voice 到 ROS（2026-09-29）

新增统一 voice-cpu-ros 门禁，具体操作与范围见 [CPU_VOICE_ROS.md](../CPU_VOICE_ROS.md)。

实现只包括 Voice 模块自有测试、平台验证工具和文档。生产 Python 模块、
原 RKLLM、默认 YAML、依赖锁、ROS package/CMake/IDL 均保持本轮开始时的内容。

## 本切片验证

两个独立进程：已安装 Voice 节点与 ROS 观察节点。domain215、localhost、唯一端点前缀。
复用原 VoiceTask 的 start/hold/release/get-state/stop，核对新会话 ID 与旧会话不同。
经真实节点处理后，通过 DDS 检查话轮 ID、会话 ID、事件来源、可执行字段，
以及实际模型输出与事件分类一致。不会直接构造预期分类来充当模型输出。

一条官方 WAV 使用真实 SenseVoice CPU，识别文本正确，再进入 Qwen 和 ROS。
其余四条明确是文本测试输入，用于 Qwen 正/负例、协议注入拒绝、词库优先。
两者分开计数，不能把五条都说成真实 ASR 录音。

## 结果解释

首轮 integration_acceptance=true；固定输入语义 4/5 符合预期。
否定句经原节点去掉标点后，Qwen 预测中性；它没有触发动作，但语义不正确。
顶层报告保留 FAIL / exit 1。此前 40 条独立意图开发集结果未覆盖、未改写。

会话停止验证只覆盖推理结束后的 stop 及不再处理捕获输入；
原同步推理时的服务阻塞/即时取消不在本切片验收范围。
不修改机器人行为、声纹身份或执行策略来使测试通过。

## 后续优先级

1. 对齐独立回放和真实节点的输入预处理，保留两种输入的差异证据；
   在独立标注集上评估否定、转述、复合意图及处理时延。
2. 增加实际机器人口令 WAV，扩展 ASR→Voice 会话→隔离 ROS 事件验收。
3. 在模型质量和取消语义明确后，接入受控 BT/Action 集成；
   保留已有 mock profile 和原 RKLLM 板端路径。
4. 视觉两张漏检、SLAM 传感器、Lite3 设备、远端 CI 与许可事项按原交接推进。

## 最终门禁

| 项目 | 结果 |
| --- | --- |
| Voice Humble 单元测试 | 417 passed，0 skip |
| 平台工具测试 | 36 passed，含真实后代进程回收 |
| 公开契约 | 25 passed |
| 架构检查 | PASS，15 ROS manifests / 21 登记接口 |
| ROS build / doctor | PASS |
| 默认本机 smoke | PASS，仍为原 mock 感知 |
| 原七仓 / 本轮生产实现与配置保护 | PASS |
| 双进程 CPU Voice ROS 链路 | PASS，5 个场景，12 次 VoiceTask 服务调用 |
| 样本语义 | 4/5，否定句失败；不作为准确率估计 |
| 完整模型 / 实机验收 | 未通过 / 未进行 |

最终运行 20260929T121237217382Z；真实音频1条、文本测试输入4条。
Qwen生成3次、输入拒绝1次；词库坐下不调用Qwen。
服务调用、原始事件、模型输出、源码指纹、资产SHA256与失败全部冻结在
validation/cpu-voice-ros，不覆盖之前的 validation/cpu-intent。

没有重复运行未改动的 Nav2 扩展、第三方构建或硬件测试；它们保留前阶段证据。
本轮无需重建依赖环境或下载模型。后续修改该模块测试文件也会影响当前平台
source_fingerprint，运行本门禁前必须更新 build-receipt。
