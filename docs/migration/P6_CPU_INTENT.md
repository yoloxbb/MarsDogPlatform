# P6 — 可选 Qwen CPU 意图（2026-09-29）

用户授权使用提供的 Qwen2.5-0.5B-Instruct，保留原 RKLLM 推理引擎。
实现、配置和复现命令见 [CPU_INTENT.md](../CPU_INTENT.md)。

## 本切片

- 新增 Voice 自有 qwen_cpu provider、惰性 CPU 引擎、自写 v2 提示词与合法标签约束。
- 原 factory 选择兼容；仅显式 type=qwen_cpu 时使用新后端。
- CPU 分类沿用现有路由和动作证据门限，保留所有旧事件/服务/ROS 类型。
- CPU 主动输入拒绝停止规则回退，关闭后的分类不会迟到进入事件链。
- 独立 intent-cpu extra / Voice lock，无跨模块导入、公共业务模块或全局 Python 环境。
- 统一 models --intent-archive 与 intent-replay 入口；固定模型、输入和源码/依赖哈希。
- 原七仓、原 RKLLM engine/provider/prompt、生产配置不动；不调用底盘或硬件。

## 验收范围

最终软件与模型检查的冻结结果记录在 validation/cpu-intent/release-manifest.json。
软件通过和模型质量未通过分别记录，不能用软件测试数替代模型精度。

模型开发集 40 条：v1 为 16/40；v2 为 21/40，保留完整失败。
v1 暴露的协议注入可执行事件已通过 CPU 输入拒绝和节点无规则回退处理。
v2 对应的限制执行用例无可执行事件，但语义仍有 19 条 exact-match 失败，
其中 1 条是明确拒绝而非错误动作预测。没有删用例或改期望来制造通过。

## 后续

保持此版本作为显式开发候选；基于独立实际口令集评估提示词/小模型适配，
核对复杂否定、转述和多意图。暂用通用 Qwen 不再受“缺少原微调权重”阻塞；
要声称与 RKLLM 等价，仍需原微调权重/训练标签与板端对照。
随后验收真实 ASR 和隔离 ROS 感知事件链，继续处理现有视觉两张漏检。
硬件、SLAM 传感器、远端 CI、厂商许可等原有限制仍存在。

## 最终软件门禁与实测

| 检查 | 结果 | 实际范围 |
| --- | --- | --- |
| Voice Humble 单元测试 | 412 passed，0 skip | 包含新后端、旧 RKLLM、词库和事件门限 |
| 平台工具测试 | 32 passed | 包含模型损坏、报告保留、源码漂移和超时回收 |
| 独立 wheel | PASS | 缺 Torch/Transformers 时仍可安装/导入，默认资源保持 |
| 架构 / 契约 | PASS / 25 passed | 15 ROS manifests、21 登记接口 |
| ROS 构建 / doctor | PASS | 安装入口、生成 IDL；未更改 package/CMake |
| 默认 / 真实 Nav2 smoke | 两者 PASS | 原感知 mock，模拟 Lite3 I/O；不是 Qwen ROS 闭环 |
| 原七仓基线 | PASS | 未修改原仓或历史 |
| 依赖兼容 | PASS | 原 Voice 37 项版本不变，新增 18 项可选依赖，其他四锁不变 |
| 最终真实 Qwen 回放 | FAIL，21/40 | 39 次生成 + 1 次拒绝；22 条限制执行样本无可执行事件 |

最终回放 20260929T114252580206Z 的源码和锁在推理前后哈希一致。
39 次生成单句耗时约 7.33–8.90 秒，中位数 7.52 秒；
这是当前 WSL float32 / 两线程观测，不是性能 SLA。拒绝输入未计入推理时延。
因此该通用小模型的当前提示词同时存在分类质量和交互时延限制。

### 保留的失败

| 用例 | 期望 | 实际 |
| --- | --- | --- |
| lie | NONE / LIE / DO | NONE / SIT / STOP |
| home | NONE / GO_HOME / DO | NONE / OWNER_RETURN / DO |
| shake | NONE / SHAKE / DO | NONE / STAND / DO |
| drop | NONE / DROP / DO | NONE / NONE / NONE |
| no-follow | NONE / FOLLOW / STOP | SCOLD / NONE / NONE |
| no-home | NONE / GO_HOME / STOP | NONE / OWNER_RETURN / DO |
| praise | PRAISE / NONE / NONE | NONE / NONE / NONE |
| comfort | COMFORT / NONE / NONE | NONE / NONE / NONE |
| owner-sad | OWNER_NEGATIVE / NONE / NONE | SCOLD / NONE / NONE |
| owner-leave | NONE / OWNER_LEAVE / DO | NONE / OWNER_RETURN / DO |
| capability | NONE / DOG_CAPABILITY / QUERY | NONE / DOG_STATUS / QUERY |
| sleep | NONE / SLEEP / DO | NONE / DOG_STATUS / QUERY |
| play | NONE / PLAY / DO | NONE / DOG_STATUS / QUERY |
| tug | NONE / TUG / DO | NONE / DOG_STATUS / QUERY |
| fetch | NONE / FETCH / DO | NONE / NONE / NONE |
| weather | NONE / NONE / NONE | NONE / DOG_STATUS / QUERY |
| statement | NONE / NONE / NONE | NONE / DOG_STATUS / QUERY |
| injection | NONE / NONE / NONE | 输入拒绝，无分类/事件 |
| mixed | PRAISE / SIT / DO | NONE / SIT / DO |

### 本切片架构复核

新业务代码只在 Voice 内；平台工具只负责准备和验证，没有增加 common 业务逻辑、
跨仓私有调用、循环依赖或新的常驻调度服务。公开 ROS 接口与原默认路径不变。
CPU 依赖保持 opt-in；模型与第三方库分别固定来源，权重保留在 out。
规则/词库、模型语义、事件可执行门限分别验证；不以格式约束代替质量验收。
保留候选与失败证据的收益是可以继续真实 CPU 集成开发，同时不悄然改变板端 RKLLM。
