# P7 团队开发与源码交付验收

工程源码：2468639054763398882366bad7869236c0d2e68e。
执行日期 2026-09-29 UTC，交接更新 2026-09-30。
结论：**PASS_WITH_EXPLICIT_LIMITS**，完成 P7a/P7b 软件目标。

## 变更与保全

初始基线 3bf529e，25 个未提交文件先备份后复核。继承开发 CLI、交付工具、
归档路径、CI 与文档工作，修正 Vision workflow 重复 run 键造成 bootstrap 丢失的问题。
其余 24 个文件内容保持原样后提交；后续只补验收证据和文档。
业务源码、五模块锁、IDL、默认运行配置及旧 validation 快照均未改变。

## 实际结果

| 门禁 | 原 WSL | 独立克隆 |
| --- | --- | --- |
| 架构/平台 | 15 ROS 包、21 接口；51 tests PASS | 相同 |
| Emotion | 218 tests + 156 subtests PASS | 相同 |
| BehaviorTree | 两棵目录；533 PASS | 相同 |
| Action | 423 PASS / 29 SKIP | 相同 |
| Voice pure | 253 PASS；排除 5 文件 | 相同 |
| Voice Humble | 430 PASS / 0 SKIP | 相同 |
| Vision Humble | 289 PASS / 3 RGA SKIP | 相同 |
| 结果契约/迁移基线 | 25 PASS | 25 PASS |
| 五模块独立 setup | 已有环境复用，prepare 保留 CPU extra | 五套新环境 PASS |
| 五模块干净 wheel 安装 | 此次在独立克隆执行 | 五项 PASS |
| 四固定 vendor | UWB 显式归档复核 | OpenVINS/VINS/UWB/RTAB 全部 MATERIALIZED |
| 默认组合 | prepare/doctor/smoke PASS | prepare、15 包从零 build、doctor/smoke PASS |
| 生命周期 | 中断、重复启动拒绝、崩溃传播、PID 回收 PASS | 此次未重复故障注入 |

Emotion 的 JUnit tests=374 含 156 subtests，不是 374 个顶层测试。
Voice pure/Humble、25 契约与单独 6 项接口检查有覆盖重叠，不能相加为独立测试总数。
Action 跳过 20 个 ROS 依赖项和 9 个 PySide2 GUI 项；Vision 跳过 3 个 RGA parity。
平台日志中的 FAIL fixture、生命周期 child_crash 的 FAIL 是预期故障注入，
对应门禁验证拒绝/传播/清理均通过。

所有工作流经过 YAML 重复键拒绝和 bash -n；本地执行 setup/test/install/check 对应命令，
Voice/Vision 还分别运行 CI 相同的 6 项冻结接口检查。**没有 hosted CI 运行记录。**

## 独立性与命令证据

克隆目录 /tmp/marsdog-developer-platform-2468639；
来源为实际主仓源码包 out/handoff/source-bundle-2468639。
系统 Ubuntu 22.04 x86_64 / Python 3.10.12 / ROS Humble 已有，不能称为全新 OS 安装。
五模块 .venv、构建工具环境、默认 15 包 colcon build/install 全部在新克隆重新创建。

明确复用的下载输入：
- uv 可执行文件及 UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv。
- prepare_ros_deps.py --cache 指向原 out/ros-deps 中的锁定 deb，仅重新校验/解包下载文件。
- 源码包内两份固定 vendor bundle。没有使用旧 vendor 源码目录补构建。
- 不复用旧模块源码 import、虚拟环境或 build/install；每套解释器路径检查已记录。

[证据总清单](../../validation/developer-platform/release-manifest.json) 列出逐文件 SHA256。
[验收摘要](../../validation/developer-platform/summary.json) 记录命令索引、源码 commit、
测试计数、skip、构建范围和限制。commands/*/execution.json 包含实际 command、cwd、
UTC 时间、Git 状态、退出码和耗时；command.log 保留完整输出。
原环境测试在提交前执行，源码内容随后固定为 2468639，再在干净克隆复验。
新构建日志保留 CMake/依赖警告，15 包完成、命令退出 0，未将 stderr 等同于构建失败。

## 交付

out/handoff/source-bundle-2468639 是本轮运行验收的源码基线包。
out/handoff/source-bundle-final 是附本轮证据和最新文档的最终包。
两包都使用干净 Git 状态导出，全 refs 历史与两份固定 vendor 归档有哈希清单；
最终包以包内 manifest 为准，代码与 2468639 一致，证据/文档为后续提交。
这些是内部本地交付，尚未上传任何外部仓库或服务。

## 限制和后续

此次没有重编 OpenVINS/RTAB/Nav2 扩展；既有验证仍保留，四 vendor 源码完整性已复核。
没有模型精度优化、实机、板端 ABI/runtime、传感器或 hosted CI 验收。
remote/访问范围、真实 owner/runner、开发板信息、Lite3 设备和部分分发许可仍 UNKNOWN。
源码包不是完全离线的依赖镜像。新成员按快速开始开发；板端须按实际系统重新构建。
