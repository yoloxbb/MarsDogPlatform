# 当前迁移状态 — 2026-09-30

**当前目标：完成统一主仓的团队开发与源码交付闭环；先 WSL2，后开发板/Lite3。**
五模块/自研 ROS/历史迁移和既有本机软件集成已完成，不重新开始合仓。
模型精度暂缓；实机、远端 CI 和板端构建分别作为后续外部阶段。
最新执行计划见 [方案 v2](../architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md) 第 15 节。

**P7a/P7b 已完成。** 工程源码提交 2468639；后续证据/文档提交见 git log。
本轮已核对保全初始 25 文件并修正 Vision CI 重复 run 键。
真实源码 bundle/独立克隆、五模块独立 setup/test/干净 wheel、51 平台测试、
25 结果契约、四 vendor 重建全部通过。干净克隆完成默认 ROS 15 包从零构建、
doctor/smoke；原 WSL prepare/doctor/smoke/生命周期门禁通过。
详见 [P7 验收](P7_DEVELOPER_PLATFORM.md) 与
[冻结证据](../../validation/developer-platform/release-manifest.json)。
源码验收包 out/handoff/source-bundle-2468639；最终包 out/handoff/source-bundle-final。
没有业务/锁/IDL/默认配置变更，没有模型精度优化或实机验收。

以下表格是阶段累计记录，其中“本轮”指对应历史阶段，不代表本次全部重新运行。
统一入口为 tools/marsdog.py。默认配置见 ../LOCAL_LITE3_CPU.md；
可选真实 Nav2 见 ../LOCAL_NAV2_CPU.md。本文件为当前状态，旧阶段记录保留在 Git。

| 阶段 | 当前状态 | 证据 |
| --- | --- | --- |
| P0/P1 架构与原始基线 | 完成；七原仓未修改，完整历史与归档保留 | architecture 提案、integration/migration/baseline、validation/real-nav2/original-sources.json |
| P2 Emotion/Needs | 历史/独立环境/安装/ROS 完成 | 19 提交；此前 218 tests + 156 subtests；P2_EMOTION.md |
| P3 BehaviorTree | 历史/接口/安装/集成完成 | 7 提交；此前 533 tests；有效 context 内退出 |
| P3 Action | 历史/接口/安装/集成完成；退出竞态修复 | 5 提交；本轮 423 pass / 29 skip；SIGINT/SIGTERM 停止与退出门禁 |
| P4 Voice | 历史/安装/ROS 完成 | 23 提交；此前 367 tests；mock 命令与可选 catalog ID |
| P4 Vision | 历史/资源/CPU 环境/ROS 完成 | 32 提交；此前 280 pass / 3 RGA skip；真实模型与相机未验收 |
| P5 新接口与航点 | 软件门禁完成 | 此前导航 31 tests + 2 subtests；本轮真实 Nav2 7 项取消/失败/恢复契约 |
| P5 Native ROS | 自研包历史/CPU 构建与功能回归完成 | 8 包历史迁移；此前 140 JUnit cases、13 CTest entries（重叠计数）；本轮补齐 behavior_ext_plugins 编译及 Nav2 加载 |
| P5 Third-party | 固定/归档/校验及所选 CPU 构建完成 | OpenVINS 4 包、RTAB 核心与 wrapper 16 包；原 OpenVINS CTest 1 项、100 个 ELF 依赖检查通过；上游完整 delta / 部分许可 UNKNOWN |
| P6 默认本机集成 | prepare/build/doctor/up/smoke 与生命周期完成 | lite3-local-cpu，10 进程 + probe；本轮回归通过 |
| P6 真实 Nav2 集成 | 实际 planner/controller/navigator + 模拟输入通过 | lite3-nav2-cpu，15 进程 + probe；GO_HOME、7 项故障恢复、生命周期通过；P6_REAL_NAV2.md |
| P6 CPU 感知回放 | 资产就绪；ASR 通过，视觉 11/13，整体 FAIL | 27 平台测试；模型与辅助 runtime 实测见 P6_CPU_MODEL_ASSETS.md、validation/cpu-model-assets |
| P6 CPU 意图 | 可选 Qwen 后端已接入；开发集 21/40，质量仍 FAIL | P6_CPU_INTENT.md、validation/cpu-intent |
| P6 CPU Voice ROS | 双进程真实 ASR/Qwen→DDS 五场景通过；已修复原文传递，整体模型未通过 | P6_CPU_INPUT_TEXT.md、validation/cpu-input-text |
| P6 CPU 软件流程 | 按用户要求不以精度阻塞；真实 Voice→BT→Action、模拟导航及推理中取消恢复已验证 | P6_CPU_FLOW.md、validation/cpu-flow |
| P6 工程门禁 | 当前软件范围通过 | 25 契约/基线检查；15 ROS manifest DAG、21 登记接口；6 项构建隔离测试 |
| P6 生产发布 / 远端 CI | 未验收 / 未配置 | 缺完整感知质量验收、原 RKLLM 等价性证据、设备、SLAM 输入、生产配置、远端和 owner 身份 |
| P7a 团队开发 / P7b 源码交付 | 完成；五环境/五wheel、真实bundle/独立克隆、四vendor、默认ROS从零构建与smoke | 2468639；P7_DEVELOPER_PLATFORM.md、validation/developer-platform |
| P7 旧代码退役 | 未进行 | 不确定生产用途的代码/launch/脚本保留，未删除原仓 |

两套运行配置共用公开接口：
Voice mock → audio_event → BT → ExecuteBehavior → Action → waypoint_nav/VoiceTask
→ 默认模拟 NavigateToPose，或可选真实 Nav2 → SUCCESS。
真实 Nav2 使用模拟地图/里程计/TF，速度只发往 /development/nav2/cmd_vel；
Lite3 I/O 同样为模拟。这两套 ROS profile 的 Vision/Voice 仍为 mock；独立 CPU 回放已使用真实权重。没有硬件控制话题发布者。
go_home 按原规则不产生 Needs 结算；不存在伪造的 BMS 电量生产者。

故障注入的单次运行 FAIL 是预期结果，门禁检查 supervisor 正确传播失败并回收 PID。
新 Nav2 profile 有序停止上层请求及 Nav2 lifecycle；Action 自己在有效 context 内完成
原有取消/停止流程。未放宽任何非零退出或导航终态断言。
本机 Cyclone loopback 小分片设置不改变旧生产 RMW 或系统网络。

当前优先级：用户明确需要可协作开发、易上手、可交付到开发板的统一主仓。
模型精度与没有硬件均不阻塞本阶段软件目标。
本轮开发入口/CI本地命令/实际源码交付与干净克隆验收已完成，证据已冻结。
后续按实际功能需求开发，或在外部信息明确后配置远端治理、板端与设备验收。
硬件、传感器、remote/owner/许可按外部条件推进，不猜测缺失实现、不退役未知入口。

最新工程/交付证据见 validation/developer-platform/release-manifest.json。
此前 CPU 流程证据见 validation/cpu-flow/release-manifest.json。Qwen SIT 被原 Lite3 门限拒绝，
词库 GO_HOME 完成模拟导航；二者不能混称为所有动作执行成功。
最新输入传递修复见 validation/cpu-input-text/release-manifest.json，固定 ROS 五场景已通过，整体模型质量仍未通过。
此前 CPU Voice ROS 切片见 validation/cpu-voice-ros/release-manifest.json，旧否定失败保留。
此前意图切片见 validation/cpu-intent/release-manifest.json，保留原 RKLLM 默认引擎。
此前模型资产证据见 validation/cpu-model-assets/release-manifest.json；
actual_inference_executed=true，但完整 model_acceptance=false，不能宣称所有模型已通过。
此前 validation/perception-replay/release-manifest.json 只确认回放基础设施。
此前 Nav2 阶段证据见 validation/real-nav2/release-manifest.json。
此前 validation/local-platform/release-manifest.json 是保留的旧验收快照，其报告哈希未改。
