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
当前主仓 git log/status 与 validation/real-nav2/release-manifest.json
提供最新源码基线；validation/local-platform 保留此前验收快照。不要根据旧阶段提案中“尚未实施”重新开始迁移。

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


## 本次继续工作 — 可选真实 Nav2

2026-09-29 新增 lite3-nav2-cpu；用 tools/marsdog.py up --profile lite3-nav2-cpu
统一启动真实 Nav2 + 现有业务模块。默认 profile 不变。
已通过真实 GO_HOME 规划/速度/位姿/Action 终态关联；7 项故障恢复契约；
两个 profile 的关闭、重复启动和子进程故障传播；25 项旧契约；6 项构建隔离测试。
Nav2 使用 domain212，OpenVINS 测试213，Action 退出测试214，默认mock210。不要并行启动同域验收。
固定 Debian 扩展依赖在 third_party/extended-ros-deps.lock.json，仅提取到 out，
未执行 apt install。独立派生元数据视图适配 CMake 绝对路径并记录哈希。

OpenVINS 四包已构建且原有腿部速度融合 CTest 通过。
RTAB 核心 0.23.8 + 全部 ROS wrapper 0.23.7，共 16 包构建通过。100 个 ELF 依赖
检查通过；已启用 OpenVINS/Qt/VTK/OctoMap，g2o/GTSAM/Ceres 优化后端未启用。
上游会向源码写 DatabaseSchema.sql，构建驱动已新增独立 out/extended-ros/vendor-source
副本；禁止放宽 vendor 校验或将生成文件加入固定快照。
tools/check_extended_ros_runtime.py 区分 ELF 依赖加载、原有 CTest 与未验证的传感器运行。
本轮唯一业务源码修复是 modules/action 的 ROS main 信号退出顺序，确保原有取消/
停止流程在 context 关闭前完成；SIGINT/SIGTERM 进程测试及 423 pass / 29 skip 通过。
robotics 自研实现、IDL、默认配置、原始七仓和算法未改。
详细操作与范围见 docs/LOCAL_NAV2_CPU.md、docs/migration/P6_REAL_NAV2.md。

下一步优先真实 CPU Vision/Voice 回放。先核对已有模型/样本资产；缺少时需要用户提供
实际路径、版本/哈希和录音/图像，不用随机模型或模拟成功冒充推理验收。
原始七仓、固定 vendor 与主机包清单已重新验证；新增阶段证据全部在 validation/real-nav2。
