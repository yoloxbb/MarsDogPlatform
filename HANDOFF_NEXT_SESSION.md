# MarsDog 平台会话交接 — 2026-09-29

当前任务：将多仓库渐进迁为可独立开发/测试、统一集成启动的平台。
用户已授权工程实施、历史迁移、普通兼容性修复；首个目标明确为 Lite3，
暂用本机 CPU，尚无设备，模块启动命令需要合并。

**最新可执行结论（后文各“增量”保留历史，以下优先）：**

- 统一启动已完成；真实 CPU Voice→隔离 ROS 输入修复后 5/5，12 次服务调用通过。
- Voice 424/0 skip、平台 36、契约 25、wheel/build/doctor/默认 smoke 通过。
- Qwen v2 原 40 条仍 21/40，新措辞 3/12；模型质量不通过，默认整机感知仍 mock。
- 仅 CPU provider 接收原始 ASR；原 RKLLM、规则、词库、公开事件文本和五套锁不变。
- 一次“示例移入 system”实验仍 3/12，否定分类退化，未采用；原始输出保留。
- 下一切片先验收推理期间 VoiceTask 的停止/会话响应与迟到事件，再扩大受控 BT/Action
  联调。模型误分类、视觉漏检和实际口令语料分别推进，不把接线通过等同于模型通过。
- 本轮源码、证据提交以 git log 及 validation/cpu-input-text/release-manifest.json 为准。

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
当前主仓 git log/status 与 validation/cpu-input-text/release-manifest.json
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
这是前一阶段的阻塞记录；用户随后明确授权暂用通用 Qwen2.5-0.5B-Instruct，
见下方最新增量。不能再把缺原微调权重当作开发 CPU 后端的阻塞。
RTMPose/yolo26n/2025 ASR等资产不自动变成生产选择；Pose MediaPipe是已有备选，不是YOLOv8权重转换。

工具层修复：失败推理保留在总报告，一模块失败继续另一模块，整个回放仍 FAIL。
目前两套 ROS 开发 profile 继续用感知 mock，没有提升未通过模型为默认生产输入。
平台测试27、接口契约25、架构和原七仓基线通过。业务/IDL/ROS源码未改，无需ROS重建。

下一切片：先核对原26s导出权重/提示来源、补实际标注口令与图像、拿到微调意图权重；
之后做隔离 ROS 感知事件/服务与 BT/Action 链路。硬件/SLAM/远端CI限制仍保留。


## 最新增量：用户授权的 Qwen CPU 意图后端


- 新增 Voice 自有 qwen_cpu provider、惰性 CPU 引擎、自写 v2 提示词与合法标签约束。
- 原 factory 选择兼容；仅显式 type=qwen_cpu 时使用新后端。
- CPU 分类沿用现有路由和动作证据门限，保留所有旧事件/服务/ROS 类型。
- CPU 主动输入拒绝停止规则回退，关闭后的分类不会迟到进入事件链。
- 独立 intent-cpu extra / Voice lock，无跨模块导入、公共业务模块或全局 Python 环境。
- 统一 models --intent-archive 与 intent-replay 入口；固定模型、输入和源码/依赖哈希。
- 原七仓、原 RKLLM engine/provider/prompt、生产配置不动；不调用底盘或硬件。

## 验收范围

最终软件与模型检查的冻结结果记录在 validation/cpu-intent/release-manifest.json。
软件通过和模型质量未通过分别记录，不能用软件测试数替代模型精度。

模型开发集 40 条：v1 为 16/40；v2 为 21/40，保留完整失败。
v1 暴露的协议注入可执行事件已通过 CPU 输入拒绝和节点无规则回退处理。
v2 对应的限制执行用例无可执行事件，但语义仍有 19 条 exact-match 失败，
其中 1 条是明确拒绝而非错误动作预测。没有删用例或改期望来制造通过。

## 后续

保持此版本作为显式开发候选；基于独立实际口令集评估提示词/小模型适配，
核对复杂否定、转述和多意图。暂用通用 Qwen 不再受“缺少原微调权重”阻塞；
要声称与 RKLLM 等价，仍需原微调权重/训练标签与板端对照。
随后验收真实 ASR 和隔离 ROS 感知事件链，继续处理现有视觉两张漏检。
硬件、SLAM 传感器、远端 CI、厂商许可等原有限制仍存在。

操作见 docs/CPU_INTENT.md。使用 prepare 时加 --voice-intent-cpu，以免 uv 同步移除可选依赖。
原 ZIP /home/elephant/MarsDog/Qwen2.5-0.5B-Instruct.zip 保留；固定 9 项模型文件在
out/models/qwen2.5-0.5b-instruct。不要解压其 Git/hooks，也不要把 GB 权重提交主仓。
CPU provider 已在节点中可选择；默认两个 ROS profile 仍为 mock。
软件门禁、模型 exact-match 与实机验收必须分别报告。

本轮最终软件门禁：Voice 412/0 skip，平台32，契约25；独立wheel、ROSbuild/doctor、
两套mock感知profile smoke、原七仓基线均通过。Qwen真实回放21/40，39次生成、1次拒绝，
22条限制执行样本无可执行事件；单句中位数7.52秒。不能称为质量或性能验收通过。


## 最新增量：真实 CPU Voice 到隔离 ROS

新增统一 voice-cpu-ros 门禁，具体操作与范围见 [CPU_VOICE_ROS.md](docs/CPU_VOICE_ROS.md)。

实现只包括 Voice 模块自有测试、平台验证工具和文档。生产 Python 模块、
原 RKLLM、默认 YAML、依赖锁、ROS package/CMake/IDL 均保持本轮开始时的内容。

## 本切片验证

两个独立进程：已安装 Voice 节点与 ROS 观察节点。domain215、localhost、唯一端点前缀。
复用原 VoiceTask 的 start/hold/release/get-state/stop，核对新会话 ID 与旧会话不同。
经真实节点处理后，通过 DDS 检查话轮 ID、会话 ID、事件来源、可执行字段，
以及实际模型输出与事件分类一致。不会直接构造预期分类来充当模型输出。

一条官方 WAV 使用真实 SenseVoice CPU，识别文本正确，再进入 Qwen 和 ROS。
其余四条明确是文本测试输入，用于 Qwen 正/负例、协议注入拒绝、词库优先。
两者分开计数，不能把五条都说成真实 ASR 录音。

## 结果解释

首轮 integration_acceptance=true；固定输入语义 4/5 符合预期。
否定句经原节点去掉标点后，Qwen 预测中性；它没有触发动作，但语义不正确。
顶层报告保留 FAIL / exit 1。此前 40 条独立意图开发集结果未覆盖、未改写。

会话停止验证只覆盖推理结束后的 stop 及不再处理捕获输入；
原同步推理时的服务阻塞/即时取消不在本切片验收范围。
不修改机器人行为、声纹身份或执行策略来使测试通过。

## 后续优先级

1. 对齐独立回放和真实节点的输入预处理，保留两种输入的差异证据；
   在独立标注集上评估否定、转述、复合意图及处理时延。
2. 增加实际机器人口令 WAV，扩展 ASR→Voice 会话→隔离 ROS 事件验收。
3. 在模型质量和取消语义明确后，接入受控 BT/Action 集成；
   保留已有 mock profile 和原 RKLLM 板端路径。
4. 视觉两张漏检、SLAM 传感器、Lite3 设备、远端 CI 与许可事项按原交接推进。

统一命令 python3 tools/marsdog.py voice-cpu-ros，前提模型已准备且 build 非 stale。
域215、唯一 /development/voice_cpu_<uuid> 前缀，两进程无硬件。
没有改生产源码/默认配置/锁/IDL。新验证器仅在 modules/voice/tests 与 tools。
模型质量失败不能报告为整机感知通过；保留旧 cpu-intent 的21/40和所有失败。

本轮最终：Voice417/0skip、平台36、契约25、架构/build/doctor/默认smoke/原七仓均通过。
CPU Voice ROS链路5场景/12次服务通过；固定输入语义4/5，否定失败仍使顶层exit1。
报告 validation/cpu-voice-ros，生产代码/配置/锁/IDL无改动。


## 最新增量：CPU 原始 ASR 文本传递修复

此前否定句失败已经定位为输入差异，详见 docs/migration/P6_CPU_INPUT_TEXT.md。
CPU provider 新增 preserve_asr_text=true；节点只对它传原始 ASR 文本。原 RKLLM、
规则回退、词库、动作证据门限和对外 asr_text 保持原清理行为；不改提示词/权重。
真实 CPU ROS 五场景已重新通过，原语义失败快照不覆盖。无标点输入仍可能错，
“你会坐下吗？”在原文/清理文本中都错分为 STOP，不能宣称全面修好否定/询问。
原40条及新增12条诊断均保留原始预测与失败，最终结果见 validation/cpu-input-text。
原同步推理的中途会话控制尚未验收，先验证它与独立口令质量，再扩大 BT/Action 联调。

本轮回归：424/0skip Voice、36平台、25契约、wheel/build/默认smoke/原七仓均通过；
原40条仍21/40且预测逐条不变，新增12条仅3/12。11条限制执行输入无可执行事件。
不能把固定ROS五场景通过误认为模型质量达标；原模型对询问、转述和情绪仍会错分。

本轮另做一次离线提示词布局对比：同样规则/37 示例移入 system，仍 3/12，
部分否定被错分为 DO，但现有门限拦截、没有可执行事件；未采用，正式 v2 不变。
新增诊断集已用于该实验，不再视为未见过的留出集。完整脚本/报告冻结在
validation/cpu-input-text/experiments/system-examples，不将实验当作 ROS 或模型验收。
