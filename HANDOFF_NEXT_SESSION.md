# MarsDog 平台会话交接 — 2026-09-29

当前任务：将多仓库渐进迁为可独立开发/测试、统一集成启动的平台。
用户已授权工程实施、历史迁移、普通兼容性修复；首个目标明确为 Lite3，
暂用本机 CPU，尚无设备，模块启动命令需要合并。

当前完成：五个 Python 模块 + 八个自研 ROS package 的历史迁移；
七原仓完整归档且未修改；RTAB/OpenVINS/VINS/UWB 固定外部快照；
独立锁文件、公开接口登记、DAG/import 门禁；
Lite3 本机 prepare/build/doctor/up/smoke 统一入口；
实际跨进程 GO_HOME 成功、正常关闭、重复启动拒绝与子进程故障传播。
这是本机软件交付；已补真实 CPU 回放，但视觉存在 2 张漏检，不是实机/完整感知发布。

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
当前主仓 git log/status 与 validation/cpu-model-assets/release-manifest.json
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

后续需要输入才能做的工作：原微调 RKLLM 权重及机器人实际录音图像、Lite3 外部 IDL/SDK 和设备、
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

## 最新增量：CPU 感知回放入口

tools/marsdog.py replay --manifest /absolute/path/to/cpu-replay.json 已实现；
--check-only 仅做资产校验。模板 config/replay/cpu.example.json，说明
docs/CPU_PERCEPTION_REPLAY.md。status=READY 不等于模型推理通过。
模型缺失返回 BLOCKED_MISSING_ASSETS / exit 2；该段是前一轮缺资产时的历史记录。

首切片是 YOLOE 物体检测 + SenseVoice/Paraformer 的已切分 WAV ASR和精确词库 payload。
不会启动 ROS/硬件，不覆盖完整 Vision、Voice 会话/VAD/KWS/RKLLM，不替换旧 mock profile。
两模块各自 replay.py 复用已有 provider，显式可选 CPU 参数，不改默认参数和生产 YAML。
平台只做哈希/标注清单、子进程与报告；五套环境/lock保持独立。

软件回归：Vision 289 pass / 3 RGA skip；Voice 380 pass；平台19项（含旧6项）；
25契约、15 ROS manifests/21接口；wheel和ROS构建、两套profile smoke通过。
实际模型推理尚未验收。新证据 validation/perception-replay，旧冻结报告未覆盖。

此前已递归核对工作区，彼时未发现权重；用户本轮已补充 models.zip，见下方最新增量。
后续优先接收实际 CPU 模型、tokens/标签、带预期答案的 PCM16 单声道16k WAV和图像。
不要下载随机替代权重或把 Action 展示媒体当感知标注集，也不要因缺模型反复搬代码。

## 最新增量：已接收模型并执行 CPU 推理

用户提供 /home/elephant/MarsDog/models.zip，SHA256
6160bd0aa7944a22aa11ac024746930e2a2fa5e04b32f7e2c318db9d3c6785a6，原包保留。
详细记录 docs/CPU_MODEL_ASSETS.md、docs/migration/P6_CPU_MODEL_ASSETS.md，
证据 validation/cpu-model-assets。不要再报告“工作区没有模型”。

统一准备：
python3 tools/marsdog.py models --model-archive /home/elephant/MarsDog/models.zip --download
统一回放：
python3 tools/marsdog.py replay --manifest out/models/cpu-20260929/cpu-replay.json
辅助检查：
python3 tools/check_cpu_model_runtimes.py --assets out/models/cpu-20260929

57 项包内 CPU/资源文件、7 项官方网络资产锁定 URL/大小/SHA256。
资产位于 out/models/cpu-20260929；所有五个 Python 环境/lock 保持原状。
CLIP 只用于准备进程的临时 PYTHONPATH，生成包含原 18 类和 end2end=false 的 26s CPU权重。
不需要再次在线编码，也没有自动安装依赖。重复准备验证后复用。
各模块独立清单 voice-replay.json / vision-replay.json 也由准备工具生成。

实际结论：SenseVoice 中文官方参考 PASS；YOLOE 13 张正例 11 PASS / 2 FAIL。
失败 000000000307 / 000000000394 都确实包含狗，不能删样本、降断言或改提示/阈值制造通过。
脸/姿态/VAD/声纹/KWS/手部已做有限 runtime 探测；手部照片没检出手，KWS 0命中；
这些只能证明文档所列的运行/负例/自匹配范围，不能称为召回/身份准确率通过。
姿态初次半身图失败保留，补充全身图通过，未宣称修好了半身输入。

CPU 26s 来自官方同系列基础权重；与原 RKNN 训练权重等价仍 UNKNOWN。
RKLLM 是专门微调的 SOCIAL|INTENT|CONTROL 分类器，原 HF/PyTorch 权重/tokenizer 缺失。
已询问用户原始权重/训练记录，未收到答复；不要下载通用 Qwen 猜测替代。
RTMPose/yolo26n/2025 ASR等资产不自动变成生产选择；Pose MediaPipe是已有备选，不是YOLOv8权重转换。

工具层修复：失败推理保留在总报告，一模块失败继续另一模块，整个回放仍 FAIL。
目前两套 ROS 开发 profile 继续用感知 mock，没有提升未通过模型为默认生产输入。
平台测试27、接口契约25、架构和原七仓基线通过。业务/IDL/ROS源码未改，无需ROS重建。

下一切片：先核对原26s导出权重/提示来源、补实际标注口令与图像、拿到微调意图权重；
之后做隔离 ROS 感知事件/服务与 BT/Action 链路。硬件/SLAM/远端CI限制仍保留。
