# MarsDog Platform

MarsDog 自研软件主仓。五个 Python 模块和八个自研 ROS package 已按历史迁入；
原始七仓库完整保留，RTAB-Map/OpenVINS/VINS/UWB 以固定外部快照管理。
当前交付是 **Lite3 本机 CPU 开发与集成版本**，尚不等于实机发布。

在当前 WSL Ubuntu-22.04 中：

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py up
~~~

另有已接入真实 Nav2 的可选本机配置：

~~~bash
python3 tools/marsdog.py up --profile lite3-nav2-cpu
~~~

范围与复现步骤见 [真实 Nav2 CPU 验收](docs/LOCAL_NAV2_CPU.md)。
定位/运动/地图仍为模拟输入，未完成实机及完整感知验收。

已接收 models.zip，并接入官方 CPU 权重。先准备带哈希和标注的资产清单：

~~~bash
python3 tools/marsdog.py models --model-archive /home/elephant/MarsDog/models.zip --download
python3 tools/marsdog.py replay --manifest out/models/cpu-20260929/cpu-replay.json --check-only
python3 tools/marsdog.py replay --manifest out/models/cpu-20260929/cpu-replay.json
~~~

见 [CPU 模型实测](docs/CPU_MODEL_ASSETS.md)及 [CPU 感知回放](docs/CPU_PERCEPTION_REPLAY.md)。
SenseVoice 中文参考已通过；YOLOE 13 张正例有 2 张漏检，整体回放仍返回 FAIL。
模型准备不代表质量验收，默认启动 profile 继续使用显式感知 mock。

Ctrl-C 关闭整组进程。日志/配置副本/数据写入 out/local/runs；
子进程崩溃会使组合失败退出，重复启动会被拒绝。详细说明见
[本机启动与验收](docs/LOCAL_LITE3_CPU.md)。

~~~bash
python3 tools/marsdog.py doctor
python3 tools/marsdog.py smoke
python3 tools/check_local_lifecycle.py
python3 tools/check_architecture.py
python3 tools/check_contracts.py
~~~

源码改动后运行 python3 tools/marsdog.py build。首次环境准备使用
python3 tools/marsdog.py prepare --uv /path/to/uv --archive-dir /path/to/archives。
已有 Ubuntu 22.04、Python 3.10、ROS Humble 是前提；工具不修改系统 ROS 或生产启动。

当前没有设备。两套整机开发 profile 的 Vision/Voice 使用明确的原有 mock provider，
相机/地图/Nav2/Lite3 I/O 使用开发替身；真实模块进程、ROS 消息、服务、
BT 仲裁、Action 导航阶段和结果链路参与验收。未验证动作仍按原规则拒绝，
不会绕过底盘门限或将模拟电量用于 Needs 结算。

代码位置：

| 领域 | 位置 | 说明 |
| --- | --- | --- |
| Vision / Voice | modules/vision、modules/voice | 原有 namespace、ROS package、服务类型与资源 |
| Emotion / Needs | modules/emotion | marsdog_core + marsdog_ros2；独立状态权威 |
| BehaviorTree | modules/behavior | 全局选择、抢占、会话与业务结果 |
| Action | modules/action | 技能阶段、执行终态、导航/外部硬件适配 |
| Native ROS / waypoint | robotics/ros2/src | 驱动、定位、跟随、避障、导航接入；保留现有包名 |
| 公共契约 | interfaces | 新提供的 IDL、接口 registry、电量证据和外部边界 |
| 构建 / 环境 / 集成 | platform、tools、integration、config | 仅工具与组合，不承载业务算法 |
| 第三方 | third_party → .external | 固定来源/提交/哈希，保留定制 fork |

每模块保留独立 pyproject.toml、uv.lock、.venv。Emotion/BT 的 ROS 可选依赖为
NumPy 1.26.4；Action 保持 2.2.6；Vision/Voice 保持 1.x。没有根 uv workspace。
普通模块测试可在各自目录用 .venv/bin/python -B -m pytest 运行；
Voice/Vision 的完整 ROS 依赖单测分别用 tools/check_voice_tests.py --mode humble
和 tools/check_vision_tests.py。构建工具是独立的 platform/humble-build-tools。

原生 CPU 回归：

~~~bash
python3 tools/check_robotics.py --uwb-source .external/uwb --output out/robotics-check
~~~

该门禁编译八个包并运行已有功能测试；完整 Nav2 插件、RTAB-Map、硬件和模型验收
另行记录。当前主仓无远端、无 hosted CI 运行；已提交 CI 配置与 owner 角色，
不冒充配置了真实 CODEOWNERS 账号。

继续开发先读 [AGENTS.md](AGENTS.md)、
[当前状态](docs/migration/STATUS.md)、
[会话交接](HANDOFF_NEXT_SESSION.md)、
[已落地架构自审](docs/architecture/PLATFORM_IMPLEMENTATION_REVIEW.md)。
原提案作为历史文档保留，未实施措辞不代表当前状态。
