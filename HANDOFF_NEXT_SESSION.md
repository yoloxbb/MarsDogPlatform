# MarsDog 平台会话交接 — 2026-09-29

## 最新目标与执行入口

用户最终目标：统一主仓与架构，使跨模块功能开发、提交合并、新成员上手更容易；
当前在 WSL2，无硬件，后续在开发板重新构建并接入 Lite3。模型精度暂不阻塞。
用户已授权普通工程决策直接执行，无需逐项确认。用户自行创建新会话。

先读：
[当前正式方案](docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md)；
用户指定的同步文件为 /home/elephant/MarsDog/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md。
**按该方案第 15 节接着完成，不要重做 P1/合仓或回到模型准确率优化。**

## 真实工作区

- WSL Ubuntu-22.04，主仓 /home/elephant/MarsDog/marsdog-platform。
- 客户端 C:\home\elephant\MarsDog 并非实际 Linux 主仓位置。
- 原仓聚合 /home/elephant/MarsDog；原仓保持只读。
- 历史归档 /home/elephant/MarsDog/migration/archives。
- uv /home/elephant/MarsDog/migration/.tools/uv。
- 下载缓存 /home/elephant/MarsDog/migration/.cache/uv（允许显式复用）。
- Python /usr/bin/python3.10；ROS /opt/ros/humble。
- 当前 main 已提交 HEAD 3bf529e；没有 remote。
- 本轮新增与修改文件尚未提交，git status 为准，禁止覆盖、丢弃或另建主仓。

## 已完成的基础

五个 Python 模块 + 八个自研 ROS package、公共 marsdog_interfaces、waypoint_nav
已迁入；原始历史/归档/commit maps 保留。RTAB/OpenVINS/VINS/UWB 固定外部快照。
模块独立锁与环境；接口登记、依赖 DAG、结果契约和独立安装检查已建立。

统一本机入口 tools/marsdog.py prepare/build/doctor/up/smoke。
默认 lite3-local-cpu（domain210）、可选 lite3-nav2-cpu（domain212）已有软件证据。
Nav2 是真实进程，但定位/地图/运动/Lite3 仍为模拟；两 profile 感知默认 mock。
独立真实 CPU Voice 流程已有证据，原 RKLLM 保留，不调模型精度。
Qwen SIT 被原动作门限拒绝、词库 GO_HOME 模拟导航成功，不能说成实机坐下成功。

最近冻结证据 validation/cpu-flow/release-manifest.json，
对应源修复 f102172、证据提交 3bf529e。旧模型质量失败记录保持，不能改写成通过。

## 本轮进行中：开发与交付闭环

已写但尚待真实端到端验证与提交：

- tools/dev.py 和 platform/modules.json development recipes：独立 setup/test、统一 check。
- tools/source_handoff.py：干净 Git 历史 bundle、refs/哈希、可选固定 vendor 归档。
- 归档查找改为 --archive-dir → MARSDOG_ARCHIVE_DIR → .cache/vendor-archives，
  活动工具不默认依赖旁边的旧 migration 目录。
- README、CONTRIBUTING、AGENTS、docs/development、docs/deployment、PR 模板。
- 六个 workflow 复用开发命令；原安装检查保留。
- 两个新平台测试文件验证环境/报告/真实 Git 往返和破坏保护。
- 架构方案、STATUS 与本交接更新。

已实际运行 python3 -B tools/dev.py check：架构检查通过，平台 51 tests / OK。
日志 out/developer-platform/dev-check-initial.log。
**尚未用新 CLI 跑完各模块真实测试，尚未实际主仓导出或干净克隆验收。**
不要把工具单测里的 Git fixture 往返当作实际交付包验收。

业务模块源码、五套依赖锁、公开 IDL、生产 YAML、默认 profile 本轮未改。
没有新增运行业务 common 或硬件协议。

## 下一步执行顺序

1. 读取 git diff/新增文件，复核 setup/test recipes 与原命令等价；
   注意 BT 两棵测试目录、Voice optional extras、跳过/失败报告和退出码。
2. 用新 CLI 实际测试 emotion/behavior/action/voice（pure 和 Humble）/vision。
   不意外重同步已有 Voice CPU extra；需要时明确 --intent-cpu 或 --voice-intent-cpu。
3. 验证工作流与本地命令一致、受影响安装/契约门禁，修复真实问题。
4. 审查后提交源码切片；工具要求 dirty 工作树不得导出正式 bundle。
5. 导出实际主仓、验证、在不依赖旧源码的位置干净克隆；
   显式复用下载缓存可以，借用旧仓 import 不可以。
6. 新克隆至少验证平台检查、Emotion/BT/Action 独立 setup/test/结果契约和 vendor materialize；
   按资源扩大安装与本机整机验证，精确记录 fresh build 或已有构建回归的范围。
7. 原 WSL 执行 doctor/默认 smoke，检查准备工具显式归档路径。
8. 冻结新证据 validation/developer-platform，更新状态并提交。
   不覆盖 validation/cpu-flow 等既有快照。

具体命令、验收定义与风险见正式方案第 15 节。
当前支持 WSL x86_64；源码交付不含模型、环境、build/install，
不能直接将这些二进制文件复制到未知开发板。

## 尚需外部条件

remote URL/公开范围、真实 owner 账号、板端 OS/ABI/NPU/SDK、Lite3/传感器设备、
部分厂商内容分发许可 UNKNOWN。它们不阻塞当前软件主仓开发。
不得虚构 hosted CI、板端成功或缺失运控/嵌入式实现。
明显机器人行为改变、不兼容协议、不可恢复历史/数据删除、未知生产入口退役，
才需要相应明确决策。普通工程实施继续自主完成。

本文件此前的逐轮模型实验叙述保留在 Git 历史：
git show 3bf529e:HANDOFF_NEXT_SESSION.md。其旧“下一步”不代表当前计划。
