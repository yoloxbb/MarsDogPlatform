# MarsDog 平台会话交接 — 2026-09-30

P7 团队开发与源码交付已完成。当前正在按用户授权进行五模块兼容性重构，
首片 R1 声音契约与 BT 无状态校验提取已落地，见
[当前路线](docs/architecture/COMPATIBILITY_REFACTOR.md)。
不要重新迁移，不做模型精度优化；导航/避障内部实现留给其负责人。
普通工程决策可直接推进。

## 真实位置与版本

- 唯一主仓：/home/elephant/MarsDog/marsdog-platform（WSL Ubuntu-22.04）。
- P7 工程源码：2468639054763398882366bad7869236c0d2e68e；交付基线 3f50614。
- 当前新源码分支：refactor/audio-contracts；R1 提交与证据以 git log 和
  validation/compat-refactor/r1 为准，不能将旧 P7 bundle 当作最新源码。
- 继续前核对 git status --short 和 git log -3 --oneline，保留任何新出现的用户改动。
- 初始 25 个未提交文件已备份、复核并纳入源码提交；仅修正 Vision CI 重复 run 键。
  备份在 out/developer-platform/initial-worktree，保全证明随验收证据冻结。
- 原仓/归档/映射保留；没有第二主仓，没有远端，没有真实 CODEOWNERS 账号。

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

源码验收包：out/handoff/source-bundle-2468639。
最终源码包：out/handoff/source-bundle-final（含本轮证据及最新交接）。
用可信 tools/source_handoff.py verify 后克隆，以 manifest 的 commit/哈希为准。
没有复制模型、虚拟环境、构建输出；包不是完整离线依赖镜像。

本机工具参考：uv /home/elephant/MarsDog/migration/.tools/uv；
显式缓存 /home/elephant/MarsDog/migration/.cache/uv；
原归档 /home/elephant/MarsDog/migration/archives。
新开发者可配置自己的路径，不要求原仓位于旁边。
已有 Voice 带 CPU extra；以后同步必须明确 --intent-cpu / --voice-intent-cpu。

## 后续工作

R1 已有 46 个声音跨进程兼容场景、BT 无状态校验模块和 CI 门禁；
重构前基线固定在 interfaces/application/audio-event-v2/baseline.json，
测试不得自动刷新基线。继续 R2 视觉链路，再处理 R3 状态/动作结果与 R4 节点职责拆分，
每片先冻结行为再改代码，保留领域边界和独立环境。R2–R4 尚未完成。
新门禁：python3 tools/check_audio_contracts.py；已有结果门禁继续保留。
只有以下外部事实到位后才做对应工作：remote URL/公开范围、真实 owner/runner，
板端 OS/ABI/NPU/SDK，Lite3/传感器设备，以及部分厂商资料的对外分发许可。
没有硬件不阻塞普通开发，不虚构协议、账号或验收结论。

正式方案：docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md 第 15 节；
聚合目录 /home/elephant/MarsDog/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md 同步维护。
历史阶段叙述保留在 Git，旧“下一步”不代表当前待办。
