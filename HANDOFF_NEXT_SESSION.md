# MarsDog 平台会话交接 — 2026-10-05

日志重构已接入五模块：入口、配置、诊断与扩展见 [统一日志](docs/development/UNIFIED_LOGGING.md)，验收见 [日志 v2 重构记录](validation/logging-v2/README.md)。公共包在 packages/observability；所有模块独立锁/环境保持，ROS 构建现在含 16 个包。

P7、五模块兼容性重构 R1–R4，以及后续业务恢复/导航交接/新源码交付均已完成。见
[当前路线](docs/architecture/COMPATIBILITY_REFACTOR.md)。
不要重新迁移，不做模型精度优化；导航/避障内部实现留给其负责人。
普通工程决策可直接推进。

## 2026-10-05 GitHub 上传基线

用户授权上传到 yoloxbb/MarsDogPlatform，按私有仓库创建。
本地 main 已从 926f14b 快进到 978d263，随后只更新远端与开发入口文档；未重写历史。
上传 main 及已有 acceptance/five-module-software-20260930 标签，旧功能分支在本地保留。
所有源码及原有资源随 Git 历史交付；out、模型、虚拟环境和缓存仍排除。
下方旧交付包/分支说明属于历史证据；新开发从远端最新 main 开始。

## 真实位置与版本

- 唯一主仓：/home/elephant/MarsDog/marsdog-platform（WSL Ubuntu-22.04）。
- P7 工程源码：2468639054763398882366bad7869236c0d2e68e；交付基线 3f50614。
- 当前开发主线：main；软件验收基线标签 acceptance/five-module-software-20260930。
  main 收口时快进接收 1835707，只追加主线文档和证据；之后的 Vision 退出修复见下。原 refactor/audio-contracts
  保留在 1835707；收口证据在 validation/mainline-acceptance。R1 提交与证据以 git log 和
  validation/compat-refactor/r1 为准；R2–R4 证据在 validation/compat-refactor/r2-r4，
  最新提交以 git log 为准。不能将旧 P7 bundle 当作最新源码。
- 继续前核对 git status --short 和 git log -3 --oneline，保留任何新出现的用户改动。
- 初始 25 个未提交文件已备份、复核并纳入源码提交；仅修正 Vision CI 重复 run 键。
  备份在 out/developer-platform/initial-worktree，保全证明随验收证据冻结。
- 原仓/归档/映射保留；没有第二主仓。远端为 https://github.com/yoloxbb/MarsDogPlatform（私有），真实模块 CODEOWNERS 与专用 runner 仍待团队配置。

## P7 历史验证

见 [验收说明](docs/migration/P7_DEVELOPER_PLATFORM.md) 和
[证据清单](validation/developer-platform/release-manifest.json)。

原环境和干净克隆五模块测试一致：
Emotion 218 tests + 156 subtests；BT 533；Action 423 pass / 29 skip；
Voice pure 253（排除 5 个 ROS 文件）、Humble 430 / 0 skip；
Vision 289 pass / 3 RGA skip。平台 51 tests，结果契约 25 tests。
模块覆盖重叠和 subtests 不盲目相加，skip 不算 pass。

干净克隆已完成五套独立 setup、五个干净 wheel 安装检查、四个固定 vendor 重建，
以及默认 ROS 组合 15 包从零构建、doctor/smoke。构建/运行位于
/tmp/marsdog-developer-platform-2468639，仅复用 uv/deb 下载缓存和已有系统 Humble。
原 WSL 的显式归档 prepare（保留 Voice CPU extra）、doctor/smoke、生命周期也通过。
没有复制旧 .venv、源码 import、build/install；SLAM 扩展此次没有重编。

两套默认 profile 的感知仍为 mock；本轮只回归默认 lite3-local-cpu。
既有 CPU Voice/Nav2/模型失败证据全部保留，不改写为实机或模型通过。
业务模块、依赖锁、IDL、生产 YAML、默认 profile 与行为门限未变。

## 开发与交付

新成员先读 README、CONTRIBUTING、AGENTS、docs/development/QUICKSTART.md。
日常：python3 tools/dev.py check；setup/test 一次选一个模块；
跨模块结果修改另跑 python3 tools/check_contracts.py。

当前实测工程源码包：out/handoff/source-bundle-scenarios-ccee303。
当前最终包：out/handoff/source-bundle-scenarios-20260930-final（含当前证据和交接）。
这个既有包固定在 1835707：包内 refactor/audio-contracts 含重构，包内 main 是旧 P7。
当前本地主仓 main 已完成收口；上述旧包不含本次标签，按包内 manifest 解释分支。
旧 source-bundle-2468639 / source-bundle-final 仅为 P7 历史包。
用可信 tools/source_handoff.py verify 后克隆，以 manifest 的 commit/哈希为准。
没有复制模型、虚拟环境、构建输出；包不是完整离线依赖镜像。

本机工具参考：uv /home/elephant/MarsDog/migration/.tools/uv；
显式缓存 /home/elephant/MarsDog/migration/.cache/uv；
原归档 /home/elephant/MarsDog/migration/archives。
新开发者可配置自己的路径，不要求原仓位于旁边。
已有 Voice 带 CPU extra；以后同步必须明确 --intent-cpu / --voice-intent-cpu。

## 新业务场景与独立交付验收

工程源码 ccee303，之后仅追加文档/证据；最终包版本以 manifest 为准。
业务矩阵：docs/development/BUSINESS_SCENARIOS.md；
导航交接：docs/development/NAVIGATION_HANDOFF.md；
本轮证据：validation/scenario-delivery/DELIVERY.md、delivery-manifest.json。

新增 check_business_scenarios.py 七项安装后 ROS 场景：
Voice hold/renew、停止后的旧请求隔离、租约过期、重启重新发现；
Vision 暂停超时/陈旧缓存、恢复后迟到回复不重复完成、重启新 epoch/target_id。
使用真实服务、DDS、安装后的 BT 感知适配器和 mock 生产者；
完整 BT 仲裁/Action/Needs 由既有单测、结果契约和全链路 smoke 承担。

主仓和独立克隆均通过 79 平台测试及七场景。
克隆 out/scenario-delivery/clean-clone-ccee303 从包创建，五环境及 ROS 15 包重新构建；
全部声音/视觉/状态/任务/结果契约、doctor/smoke 和取消 transport 通过，
所有记录进程正常退出且无残留。只复用 uv/deb 下载缓存及系统 Humble；
原 WSL Voice CPU extra 未动。未重复运行不涉及的全量五模块/wheel/SLAM 扩展，
对应 R2–R4 历史证据仍有效且未改写。

本轮业务模块、导航/避障、IDL、生产配置、依赖锁和运动门限未改。
不把 mock 进程暂停描述为真实相机断流，不把 source package 作为完整离线依赖镜像。
已准备好导航负责人交接文档，没有发送外部消息。

## 最近 ASR / Action 试用

用户试用时发现原 CPU flow 在 Vision 退出阶段触发 Humble wait-set / context 竞态。
已精确处理仅发生在 context 关闭后的对应 RCLError；其他运行错误仍失败。
八种回归从 1 fail / 7 pass 到全通过；Vision 297 pass / 3 RGA skip，
平台/视觉/任务/wheel/build、真实 CPU flow 与七项恢复通过。证据：
validation/voice-action-trial/README.md。原 mainline 标签和旧包固定不变，
此修复是基线之后的普通功能分支增量，不能再声称最新 main 只有文档变化。

当时的启动说明见 docs/CPU_SOFTWARE_FLOW.md。该轮入口为固定分段回放：
一条真实普通 WAV + 明确文本命令，回家文本可到 Action 并模拟导航成功；
该轮尚未验证真实麦克风/用户音频口令到动作。新增 WAV 入口见下方 P0–P2。WSL 缺 PortAudio，PATH 无 arecord；
设备探测未录音，没有放宽 Lite3 动作限制。

## 后续工作

R1–R4 已完成，不再把视觉、状态/动作和节点拆分列为待办。
统一入口 interfaces/application/README.md；组件职责见当前路线。
R2–R4 历史验收平台 71 项、Voice 430、Vision 289 + 3 skip、Emotion 218 + 156 subtests、
BT 533、Action 423 + 29 skip；另有 35 ROS 动作回调 0 skip。
音频 46、视觉 33、状态 34、任务 18 × 2、结果 25 契约通过；
五个 wheel / 18 组件、默认 ROS 构建和 smoke、DDS 取消归属及退出清理均通过。
跳过、硬件、模型和远端 CI 限制见 validation/compat-refactor/r2-r4/README.md。
正常测试只读冻结 baseline.json，禁止为消除差异自动刷新。
后续在本仓按实际功能需求开发，不建立新的跨领域业务 common。
只有以下外部事实到位后才做对应工作：remote URL/公开范围、真实 owner/runner，
板端 OS/ABI/NPU/SDK，Lite3/传感器设备，以及部分厂商资料的对外分发许可。
没有硬件不阻塞普通开发，不虚构协议、账号或验收结论。

正式方案：docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md 第 15 节；
聚合目录 /home/elephant/MarsDog/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md 同步维护。
历史阶段叙述保留在 Git，旧“下一步”不代表当前待办。

## P0–P2：录音、诊断、能力与功能开发入口

本轮从 90b16be 创建 feature/recording-diagnostics-p2；实际提交以 git log 为准。
接手前核对工作区，不重复实现本节。验收见 validation/recording-diagnostics-p2。

- P0：marsdog.py trial --wav 接任意合规预切分 WAV，通过真实 CPU ASR 和安装节点 DDS，
  输出 HTML / JSON 时间线。BT 诊断现由统一日志 v2 采集，使用原会话/语句/Goal 身份，不新增 wire 字段。
- P1：capabilities 由现有词库/映射及 Action 自身策略生成；125 路由中 49 条缺失模板照实保留。
  check_decision_scenarios.py 五场景通过，覆盖去重、排队、停止抢占、目标过期、Needs/Emotion 仲裁。
- P2：new-feature 生成未激活草稿、配置落点、三侧契约测试与 NOT_RUN 验收清单；
  未实现的 Voice/BT 正向模板已实测会失败，不是空断言。

文档：docs/development/RECORDING_TRIAL.md、FEATURE_WORKFLOW.md；
诊断定义：interfaces/observability/README.md（v2 已替代原 decision trace）。
本机合成“回家”音频可经真实 ASR 完成模拟导航；“坐下”正确保留原 Lite3 门限拒绝。
没有用户麦克风/实机/模型精度验收，没有改默认配置、IDL、依赖、需求结算或导航避障内部。
本次新增开发工具与已完成迁移/重构是不同层次的增量，不要再做迁移。


## 日志系统 v2

在 refactor/unified-logging 上继续重构，用户授权放弃旧日志格式。
公共包 0.2.0 / envelope v2：一个进程一个异步 JSONL 写入器，context 独立保存身份；
不再维护 Voice/Vision TRACE、BT JSON 或 decision-trace 文件。
Action 正式执行回调负责唯一 completed 记录，异常原样传播并记录 crashed。
ROS 原生日志经独立 /rosout 收集器归一化；业务协议、动作门限与导航内部不变。
使用说明 docs/development/UNIFIED_LOGGING.md；验收 validation/logging-v2。
旧 validation/unified-logging 是 0.1.0 历史结果，不代表现行格式。
