# MarsDog Platform

MarsDog 的统一开发主仓：视觉、语音、Emotion/Needs、行为树、Action 和自研 ROS
模块在这里开发、测试和提交。五个 Python 模块仍有独立包、锁文件和环境。
原仓历史已迁入并保留来源记录；后续功能直接在本仓完成一个可评审的变更。

当前支持 **WSL2 / Ubuntu 22.04 / Python 3.10 / ROS Humble 的 Lite3 CPU 开发环境**。
没有实机；本机集成用明确的设备替身。开发板的系统、ABI、NPU SDK 尚待确认。
目标是先完成软件协作和集成，再在板端构建、接入 Lite3。

当前开发主线为 main，软件验收基线标签为
acceptance/five-module-software-20260930。
后续功能从该主线创建分支；[收口记录](validation/mainline-acceptance/README.md)说明版本与验证范围。

## 从这里开始

- 新成员：[开发快速开始](docs/development/QUICKSTART.md)
- 新功能、提交与合并：[贡献指南](CONTRIBUTING.md)
- 模块边界与跨模块变更：[开发流程](docs/development/WORKFLOW.md)
- 事件、行为、仲裁与动作：[当前系统详图](docs/architecture/EVENT_BEHAVIOR_ACTION.md)、[配置索引](docs/architecture/EVENT_BEHAVIOR_ACTION_INDEX.md)
- 真实录音到动作：[WAV 试用与诊断](docs/development/RECORDING_TRIAL.md)
- 五模块日志与会话查询：[统一日志使用说明](docs/development/UNIFIED_LOGGING.md)
- 能力缺口与新增功能：[能力清单和功能草稿](docs/development/FEATURE_WORKFLOW.md)
- 名称含义、兼容例外与自动检查：[标识规范及目录](interfaces/naming/README.md)
- WSL 到开发板：[源码交付与板端接入](docs/deployment/SOURCE_HANDOFF.md)
- 兼容性整合：[五模块重构路线](docs/architecture/COMPATIBILITY_REFACTOR.md)
- 业务验收：[场景矩阵与恢复门禁](docs/development/BUSINESS_SCENARIOS.md)
- 导航协作：[负责人交接](docs/development/NAVIGATION_HANDOFF.md)
- 当前事实：[迁移状态](docs/migration/STATUS.md)
- Agent / 后续会话：[AGENTS.md](AGENTS.md)、[交接](HANDOFF_NEXT_SESSION.md)

在本仓根目录执行，不需要原仓在旁边：

~~~bash
# 仅标准库：架构/接口/依赖环检查 + 平台工具回归
python3 tools/dev.py check

# 一次准备、测试一个模块；已安装 uv 时可改用 --uv /absolute/path/to/uv
python3 tools/bootstrap_uv.py
python3 tools/dev.py setup emotion
python3 tools/dev.py test emotion
~~~

其他模块名为 behavior、action、voice、vision。Voice 默认运行纯 Python 子集，
完整测试加 --ros；Vision 完整单测需要已有 Humble。
全部入口、跳过项解释和依赖安装范围见快速开始。

## 整机开发组合

准备前需已有 ROS Humble，并取得固定第三方源码归档；工具不安装系统 ROS。
`--archive-dir` 可指向任意位置，或设置 `MARSDOG_ARCHIVE_DIR`；
未指定时只查本仓 `.cache/vendor-archives`。

~~~bash
python3 tools/marsdog.py prepare --uv /absolute/path/to/uv --archive-dir /absolute/path/to/archives
python3 tools/marsdog.py build
python3 tools/marsdog.py doctor
python3 tools/marsdog.py up
~~~

Ctrl-C 关闭整组进程，日志写入 out/local/runs。
默认 lite3-local-cpu 使用感知 mock、模拟导航和设备；
`up --profile lite3-nav2-cpu` 使用真实 Nav2，定位/地图/运动输入仍为模拟。
详细准备与验证见 [本机组合](docs/LOCAL_LITE3_CPU.md)、[Nav2 组合](docs/LOCAL_NAV2_CPU.md)。

真实 CPU 感知是可选开发路径：见 [CPU 软件流程](docs/CPU_SOFTWARE_FLOW.md)、
[CPU 意图后端](docs/CPU_INTENT.md)、[模型资产](docs/CPU_MODEL_ASSETS.md)。
原 RKLLM 保留；精度改进当前不阻塞仓库整合，不自动替换默认 profile。

## 代码归属

| 领域 | 唯一开发位置 | 职责 |
| --- | --- | --- |
| Vision | modules/vision | 感知与视觉任务，发布现有事件 |
| Voice | modules/voice | 语音会话、ASR/意图、语音任务与事件 |
| Emotion / Needs | modules/emotion | 内部状态与需求结算的权威 |
| BehaviorTree | modules/behavior | 选择、仲裁、抢占与会话协调 |
| Action | modules/action | 技能阶段编排、执行终态、外部能力适配 |
| 原生 ROS / 航点 | robotics/ros2/src | 定位、跟随、避障、导航和现有驱动接入 |
| 公共契约 | interfaces | ROS IDL、接口登记、外部边界与证据 |
| 工程与组合 | platform、tools、integration、config | 构建、测试、运行组合；不承载领域业务 |
| 第三方 | third_party → .external | 固定历史快照及定制 fork；不当作自研目录 |

没有根 Python 大环境：Emotion/BT 的 ROS extra 为 NumPy 1.26.4，
Action 保持 2.2.6，Vision/Voice 保持 1.x。模块内使用自己的 pyproject.toml 和 uv.lock。
公共 ROS 类型由原 owning package 维护，现有服务/动作/Topic 身份不随目录调整而改名。

本仓已有 CI 配置，但尚无远端、真实 owner 账号或 hosted CI 运行记录。
源码离线交付保留 Git 历史；模型、构建输出、虚拟环境和设备配置不进入主仓。
