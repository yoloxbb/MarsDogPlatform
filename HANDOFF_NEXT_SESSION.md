# MarsDog 平台迁移交接

更新：2026-09-29。下一步：Vision 原锁环境与软件基线；Voice 软件迁移已完成。

## 工作目标与授权

渐进迁移多仓到长期维护的平台，保持算法、公开接口、Git 历史和模块独立性。
各模块独立 Python lock/env，ROS Humble build tools 单独环境。先测试再迁移，
禁止为目录整齐重写算法、合并冲突环境、跨模块依赖私有实现或制造循环依赖。
不臆测运控或嵌入式实现。

用户已批准按方案执行、普通工程决策及可回退的平台本地提交。原始七仓仅核对，
不得 reset/filter/改文件或改历史。未知生产代码退役、不兼容协议、重大机器人
行为变化、不可恢复删除、缺失运控协议或大规模重写才需人确认。

已批准的行为修正：自动 cancel 与 operator recovery release 分开；go_home
到达后沿用 hold-position；Action/BT/Needs 无真实电量证据时不得补充 Energy。
这些不是待审批事项，不要恢复旧行为。

## 实际环境

外层是 Windows PowerShell；真实代码在 WSL Ubuntu-22.04：
/home/elephant/MarsDog，平台仓库 /home/elephant/MarsDog/marsdog-platform。
声明的 C:\home\elephant\MarsDog 此前不存在，不要另建空项目替代 WSL 源码。
可通过 wsl.exe -d Ubuntu-22.04 -- bash 调用；工具 workdir 使用 C:\、
shell 使用 powershell.exe、login false。按正常 sandbox 审批访问 WSL。

PowerShell here-string 末尾加独立 # end，避免 bash 最后一行附加 CR；
不要在单引号 here-string 内嵌同样的终止标记。WSL 未装 rg，可用 Python/find/grep。

uv 在 /home/elephant/MarsDog/migration/.tools/uv（0.12.19）。
复用缓存：UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv。
大日志、快照、bundle 在 retained migration 工作区，不是业务源码主仓。

## 必读

1. AGENTS.md、README.md。
2. docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md。
3. docs/migration/STATUS.md、P4_VOICE.md、P4_ENVIRONMENT_GATE.md。
4. docs/migration/P5_NAVIGATION_RECOVERY.md。
5. docs/migration/ENERGY_SETTLEMENT_DECISION.md、interfaces/application/BATTERY_OBSERVATION.md。
6. integration/migration/tools/baseline_lib.py、import_verified_history.py。

## 已完成

| 模块 | 位置/状态 | 历史 |
| --- | --- | --- |
| Emotion/Needs | modules/emotion，软件验证完成 | 19 提交 |
| BehaviorTree | modules/behavior，软件验证完成 | 7 提交 |
| Action | modules/action，软件验证完成；硬件边界保留 | 5 提交 |
| Voice | modules/voice，软件验证完成；模型/板端待验收 | 23 个可达提交已归档 |
| 新 interfaces | interfaces/ros2/marsdog_interfaces | 原来源无 Git，独立 hash 基线 |
| 新 waypoint_nav | robotics/ros2/src/waypoint_nav，mock Nav2 验证通过 | 同上 |
| Vision | 原仓/快照，尚未导入 | 未创建归档 |
| robot_ws、rtabmap_ws | 原仓保持不变，完整原生 ROS/vendor 迁移尚未完成 | 未创建归档 |

Voice 导入 merge：0384a81。95 个跟踪文件、mode、配置、lock、IDL、静态资源
全部原样导入；没有改 Voice 业务源码。all-refs bundle 已恢复核对 refs/fsck；
旁支在 bundle 中保留，不表示平台 main 合入了所有旁支。
证据见 docs/migration/history/voice-import.json、voice-commit-map.txt、
validation/p4-voice/equivalence.json。最新 HEAD 请 git log -1 获取。

Voice 验证：
- 原快照和迁移后纯 Python 子集各 165 passed；
- 原快照和迁移后 Humble 全量单元测试各 328 passed；
- 165 包含在 328 内，不相加，均无 skip；
- clean wheel 原 lock、配置/launch/static hash、词库和 HTTP OpenAPI 一致；
- ROS 独立构建、已安装 mock Voice 的 7 个服务用例及 SIT DDS 事件通过；
- ROS probe 为同测试进程内两个真实节点，非完整机器人/麦克风推理；
- 初次无 ROS 的全量测试因 rclpy 缺失有 4 个收集错误，使用现有 Humble 后通过，
  未改测试或伪造 rclpy；
- CI 只覆盖 pure subset、wheel 和接口/资源保护；完整 Humble gate 为本地验证。

Voice 命令：
```bash
uv sync --project modules/voice --locked --no-install-project --extra dev --python /usr/bin/python3.10
python3 -B tools/check_voice_tests.py --mode pure
python3 -B tools/check_voice_tests.py --mode humble
python3 -B tools/check_voice_install.py --uv uv
python3 -B tools/check_voice_ros.py --uv uv
```

其他已完成验证：Action 420 passed / 29 skipped；Emotion 218 passed +
156 subtests；跨进程电量 22 cases；导航 31 tests + 2 subtests。
Behavior 曾完整跑 532 passed，后续电量新增项做了聚焦验证，不虚称最新全量数量。
报告中 skips 不是 passes。已有真实安装 Needs ROS 电量证据/重复/legacy 拒绝验证，
但仍无真实电池 producer，不是充电闭环。

## 仍需保持的运行边界

Voice 保持 marsdog_voice_interaction ROS namespace、String/JSON 音频事件、
VoiceTask service，waypoint_nav 暂继续借用该服务类型，不改 wire interface。
纯 Python wheel 不提供生成的 srv 或 ARM 库；ROS install 另行验证。
不要调用生产配置的 main 来检查 console script。

Voice 模型路径依 YAML 目录解析：新位置的 ../../models 默认指向平台 modules/models，
不再是原 aggregate/models。配置原字节不变不等于部署路径等价。没有搬迁模型或
声纹数据。生产切换前用明确外部 config_path、原 storage.root 和模型路径，
明确 MARSDOG_PYTHON 指向 Voice .venv。lib/librkllmrt.so 是保留的第三方 ARM64
二进制，来源版本/许可证据 UNKNOWN；不要在 x86 执行或当成自研代码。

默认 Fast DDS discovery 问题仍未解决；隔离测试用已有 loopback UDP profile，
不能代替生产部署验收。无 remote/hosted CI、无生产 profile、无真实 owner 账号。
不编造 CODEOWNERS，不宣称模型/设备/底盘/充电硬件验收完成。

## 下一步执行顺序

1. 核对 git status、原七仓冻结基线和新导航来源基线，不能重 capture 掩盖变化。
2. 读取 Vision 原 pyproject/uv.lock、README、测试，确认入口和模型/硬件边界。
3. 复用独立快照恢复 Vision 原锁环境；Voice 网络已恢复不能证明大体积 Torch
   所需文件全部可得。先检查缺包、磁盘空间和实际 download，再运行原测试。
4. 原测试通过后验证 clean wheel、ROS package 构建/必要的 mock 接口与资产，
   按 Voice 同样原则 archive/filter disposable clone/commit map 导入。
5. robot_ws 原生包和 rtabmap 第三方来源单独处理，再做完整集成启动与生产验收。

起始命令（WSL）：
```bash
set -e
set -o pipefail
cd /home/elephant/MarsDog/marsdog-platform
export MARSDOG_MIGRATION_WORKSPACE=/home/elephant/MarsDog/migration
export MARSDOG_LEGACY_ROOT=/home/elephant/MarsDog
export UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv
git status --short
python3 -B integration/migration/tools/check_baseline.py
cd /home/elephant/MarsDog/migration/work/p1-20260928/sources/vision
/home/elephant/MarsDog/migration/.tools/uv sync --locked --no-install-project --extra dev --python /usr/bin/python3.10
```

原七仓路径/HEAD/3074 文件等冻结于 integration/migration/baseline。
新增导航源码独立基线为 docs/migration/new_navigation_baseline.json。
原 source snapshot 在 /home/elephant/MarsDog/migration/work/p1-20260928/sources。
所有工作应先读实际代码和现有证据，重要未知明确写 UNKNOWN。
