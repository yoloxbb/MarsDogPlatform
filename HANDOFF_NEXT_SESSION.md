# MarsDog 平台会话交接 — 2026-09-29

当前任务：将多仓库渐进迁为可独立开发/测试、统一集成启动的平台。
用户已授权工程实施、历史迁移、普通兼容性修复；首个目标明确为 Lite3，
暂用本机 CPU，尚无设备，模块启动命令需要合并。

当前完成：五个 Python 模块 + 八个自研 ROS package 的历史迁移；
七原仓完整归档且未修改；RTAB/OpenVINS/VINS/UWB 固定外部快照；
独立锁文件、公开接口登记、DAG/import 门禁；
Lite3 本机 prepare/build/doctor/up/smoke 统一入口；
实际跨进程 GO_HOME 成功、正常关闭、重复启动拒绝与子进程故障传播。
这是本机软件交付，不是实机或模型推理发布。

实际工作区在 WSL，不在当前客户端显示的 C:\home 路径：

- 发行版 Ubuntu-22.04
- 主仓 /home/elephant/MarsDog/marsdog-platform
- 原仓聚合 /home/elephant/MarsDog
- 归档/缓存/原始验证工作区 /home/elephant/MarsDog/migration
- uv /home/elephant/MarsDog/migration/.tools/uv
- uv cache /home/elephant/MarsDog/migration/.cache/uv
- 系统 Python 3.10，ROS /opt/ros/humble
- Windows 可读路径 \\wsl.localhost\Ubuntu-22.04\home\elephant\MarsDog\marsdog-platform

先读 README.md、AGENTS.md、docs/migration/STATUS.md、
docs/architecture/PLATFORM_IMPLEMENTATION_REVIEW.md 和 docs/LOCAL_LITE3_CPU.md。
当前主仓 git log/status 与 validation/local-platform/release-manifest.json
提供最终源码基线；不要根据旧阶段提案中“尚未实施”重新开始迁移。

最常用命令（在主仓内）：

~~~bash
python3 tools/marsdog.py up
python3 tools/marsdog.py smoke
python3 tools/check_local_lifecycle.py
python3 tools/check_architecture.py
python3 tools/check_contracts.py
python3 tools/marsdog.py build
~~~

prepare 需要 --uv 指定上述 uv；缺源码归档时指定 --archive-dir。
Emotion/BT/Action 在自己的环境安装普通 wheel；Voice/Vision 用各自依赖环境，
ROS Python 与生成 IDL 从明确的 install 前缀加载。不要把这些环境合并。
本机 profile 用 Cyclone DDS，小分片解决当前 WSL 接收不到部分诊断 UDP 的问题；
不要改规划器频率或放宽断言来绕过。原生测试原样通过。

本轮关键窄修复：原生 C++ 两处语法错误；Emotion/BT 缺少 NumPy ROS 可选依赖；
Action config_dir 与严格本机 simulated I/O；Voice mock 缺命令与可选 catalog ID；
BT 在有效 context 内释放会话/取消并退出。详细报告与源码例外均可追溯。

验证结果：Emotion 218 + 156 subtests；BT 533；Action 423/29 skip；
Voice 367；Vision 280/3 skip；Native 140 cases 与 13 CTest entries；
导航 31 + 2 subtests；当前契约 25。不要把重叠用例加总成更多测试。
go_home 不产生 Needs 结算；不要为 smoke 人为改变这个产品语义。
模拟电量绝不能结算 Energy。

后续需要输入才能做的工作：真实 CPU 模型/录音图像回放、Lite3 外部 IDL/SDK 和设备、
完整 Nav2/RTAB 传感器与地图验收、远端与 owner 绑定、厂商许可、旧入口用途确认。
已有证据不足时标 UNKNOWN，不伪造硬件、推理或 hosted CI 成功。
仍缺运动控制算法和嵌入式仓库，只保留已有外部调用边界。

不要修改原仓、删除归档、强行重写算法、升级 vendor、放宽控制门限、改公开 ROS 类型，
也不要发布未经确认的厂商库。新增业务功能直接在主仓独立模块实现，经公开接口与
契约/集成门禁验证。不要再次大规模搬文件或创建第二个主仓。
