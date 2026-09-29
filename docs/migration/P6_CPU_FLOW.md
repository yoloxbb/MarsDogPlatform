# P6 — CPU 软件流程与推理中会话控制（2026-09-29）

用户明确暂不关心模型精度，本阶段以软件流程为验收目标。未继续修改 Qwen 提示词、
模型权重、标签或依赖，历史模型失败不覆盖。详细操作见 ../CPU_SOFTWARE_FLOW.md。

## 已证实的问题

原 Voice 单线程 ROS 回调同步执行 Qwen。新增真实模型回归中，推理约 7.3 秒，
get_interaction_state 超过 2 秒仍未完成，门禁按原断言 FAIL。
此前只在推理完成后调用 stop 的测试无法覆盖此问题。

## 兼容修复

只有显式 CPU provider 声明 background_intent；ThreadPoolExecutor 仅一个任务，
计算在后台，语义路由与发布留在 ROS 线程。保留词库优先、规则回退、拒绝输入、
原文策略、事件字段和原 RKLLM 默认路径。
提取 _complete_intent / _finish_speech_capture 复用原后处理，新增会话/唤醒核对。
停止和超时后旧结果丢弃；同一任务未结束前不采集/提交新任务，避免共享 provider 状态竞争。
不强行中断 native kernel，不修改对外 VoiceTask/ROS 协议。

单元回归覆盖停止/重启、超时、唤醒替换、后台异常、唯一完成，以及计算线程不发布事件。
真实验证观察模型开始/结束、服务响应和跨进程 DDS。首轮修复后暴露验证器自身竞态：
DDS 已到而审计快照尚未更新。验证器现在等待两份证据就绪，保留“恰好一次推理”断言，
原失败快照仍保留。

## 完整软件流程

新增 --acceptance flow：只将模型精度从通过条件中分离，原错误/标签仍在报告。
默认 strict 不变。新增 --with-behavior：复用现有本机组合，接入原 BT/Action/
Emotion/Needs 和模拟 Lite3/Nav2，通过原公共接口交互，不生成另一个业务实现。

真实 Qwen SIT 的事件/话轮/会话与 BT/Action Goal 关联；Action 的未验证 Lite3 SIT
返回明确 capability rejection，未放开旧门限。词库 GO_HOME 经过航点与模拟导航成功。
每个可执行模型事件需唯一 Goal/终态；未知执行失败、丢结果或组件异常退出不能通过。
未启用硬件发布者，Emotion/Needs 与 Vision 的范围仍受本机模拟约束。

## 验收范围

Voice 430/0 skip；平台 39；契约 25；架构、wheel、ROS build/doctor、默认 smoke、
原仓及兼容性保护分别记录在 validation/cpu-flow/release-manifest.json。
完整流程包含 1 条真实 ASR WAV 和 7 条明确文本输入，共 17 次 VoiceTask 调用。
这里只验证流程，model_acceptance / hardware_acceptance 不作通过声明。
Qwen 数值计算可在停止后继续短时间运行，其结果不能影响旧或新会话。

源码提交和原始验收报告通过哈希绑定；baseline、首轮审计竞态、首轮链路和最终链路
各自保留，不把先前失败重写为成功。旧 cpu-input-text 及更早快照不变。

## 最终实测

Voice-only strict：PASS，16 次服务调用；完整 flow：PASS，17 次服务调用。
完整链路中真实 Qwen 推理 7.330 秒；推理中的查询/停止/重启/查询分别约
2.230 / 1.761 / 1.599 / 1.521 毫秒。停止响应早于推理结束，旧话轮语义事件为零，
新会话恢复词库命令。9 个配套进程正常退出；Voice worker/observer 也已回收。
这是本次 WSL 实测，不是任意机器负载下的实时性能承诺。
