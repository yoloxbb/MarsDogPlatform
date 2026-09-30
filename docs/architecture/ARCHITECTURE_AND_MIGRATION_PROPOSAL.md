# MarsDog Architecture and Migration Proposal

**版本：2.2 · 更新：2026-09-30 · 状态：P7 交付及五模块 R1–R4 兼容性重构均已完成。**

本文是后续会话的执行计划，替代 v1 中“尚未实施、下一步 P1”的进度判断。
用户的最终目标是：把多个模块仓库整合为一个长期可维护的主仓，统一架构和工程入口，
使新功能开发、提交合并、新成员上手与整机集成都更容易；先在 WSL2 整理和验证，
后续再到开发板构建、接入 Lite3。**当前没有真实硬件，模型精度暂不作为本阶段阻塞条件。**

普通工程决策和必要实现已授权，不需要逐项确认。不要重新合仓、重新设计大框架，
也不要把工作重新收敛到提示词、准确率或缺失硬件的调试。
用户自行创建后续会话；执行者不需要创建、发送或管理其他会话。

## 0. 新会话先读：当前事实与开发入口

实际主仓是 /home/elephant/MarsDog/marsdog-platform，WSL Ubuntu-22.04。
Windows 对应路径为 \\wsl.localhost\Ubuntu-22.04\home\elephant\MarsDog\marsdog-platform。
聚合目录不是第二个 Git 主仓；新增业务开发只在主仓完成。
本文相对链接以主仓 docs/architecture 下的文件为基准，聚合目录副本同步正文。

**当前新增工作：第 15.4 节的五模块 R1–R4 兼容性重构已完成。**
Voice、Vision、Emotion、BT、Action 已拆分领域职责并统一契约查阅与测试入口；
最新源码以 git log 为准，证据见 validation/compat-refactor/r2-r4。
导航/避障内部、模型精度和实机验收未纳入本轮。
[重构结果](COMPATIBILITY_REFACTOR.md) 记录具体组件、门禁和限制。

以下为 P7 历史交付基线，不能当作包含新重构的源码包。P7 工程源码提交为
2468639054763398882366bad7869236c0d2e68e。
初始 25 个未提交文件已核对、备份并纳入该提交，只修正了 Vision CI 重复 run 键；
其余 24 个文件原内容保留。该历史交付阶段未修改业务模块、五套锁、IDL、默认运行配置或旧验证快照。

P7 阶段真实验证：新旧环境五模块测试，五模块独立 setup/干净 wheel 安装，
51 项平台测试、25 项结果契约、四个固定 vendor 重建。独立克隆还从零完成
默认组合的 15 包 ROS 构建、doctor 和 smoke；原 WSL 的 prepare/doctor/smoke
及生命周期门禁也通过。具体计数、skip、命令、环境和源码 commit 见
[P7 验收](../migration/P7_DEVELOPER_PLATFORM.md)、
[P7 冻结证据](../../validation/developer-platform/release-manifest.json)。

源码基线包位于主仓 out/handoff/source-bundle-2468639；
包含证据和最新文档的最终包位于 out/handoff/source-bundle-final，以包内 manifest 为准。
新克隆测试位置 /tmp/marsdog-developer-platform-2468639；
只显式复用 uv/deb 下载缓存、已有系统 Humble 和包内 vendor 归档，不借旧源码 import。

后续会话先读 AGENTS、CONTRIBUTING、STATUS、WORKFLOW 并核对 git status / git log。
普通新功能直接按统一入口开发；不要重新执行已完成的合仓或模型调优。
remote/真实 owner、开发板 OS/ABI/SDK、实际设备和对外分发许可仍是外部待办。

## 1. Current Architecture

### 1.1 已落地的主仓

五个 Python 领域模块、自研 ROS 包、公共接口、航点导航、集成工具和 CI 已进入主仓。
原七仓及完整档案保留，迁移映射与基线在 integration/migration、docs/migration。
RTAB/OpenVINS/VINS/UWB 使用固定外部快照，不把完整第三方算法铺进自研模块。

| 原来源 | 当前实际归属 | 状态 |
| --- | --- | --- |
| MarsDog（Vision） | modules/vision | 已迁入，保留原 Python/ROS namespace |
| MarsDogVoiceInteraction | modules/voice | 已迁入，保留 RKLLM；可选 Qwen CPU |
| MarsDogEmotion | modules/emotion | 已迁入，marsdog_core / marsdog_ros2 |
| 20260702_MarsDogTree | modules/behavior | 已迁入，保留两棵现有测试目录 |
| 20260707_MarsDogAction | modules/action | 已迁入，保留 executor / adapter |
| slam/robot_ws 的自研包 | robotics/ros2/src | 八个自研原生 ROS package 已分类迁入 |
| 后续提供的 marsdog_interfaces | interfaces/ros2/marsdog_interfaces | 已接入并登记原类型 |
| 后续提供的 slam/waypoint_nav | robotics/ros2/src/waypoint_nav | 已接入，保留 VoiceTask 兼容接口 |
| robot_ws 中 OpenVINS/VINS/UWB | third_party/sources.lock.json → .external | 固定原历史快照 |
| slam/rtabmap_ws | third_party/sources.lock.json → .external/rtabmap | 固定完整定制 fork |

v1 的 modules/navigation、modules/sensors、contracts、YAML 清单是最初规划名称，
**不能再据此搬动当前已落地目录**。实际使用 robotics/ros2/src、interfaces、
platform/modules.json、platform/ros-build.json；按实际代码和验证结果维护。

### 1.2 实际运行与边界

- Vision/Voice 发布原有感知/语音事件，提供自己的 task service。
- Emotion/Needs 消费感知、时间、触摸、结果等输入，拥有情绪/需求状态和结算。
- BehaviorTree 消费感知与需求状态，选择、仲裁、抢占，并协调会话与目标。
- Action 执行技能阶段，调用导航、跟随、外部硬件适配，返回反馈/终态。
- BT 把执行事实映射为现有业务结果，Needs 按原规则处理；不是所有动作都结算需求。
- Action 包含部分速度级局部控制和适配，但不存在已知关节级运控算法仓或嵌入式仓。
- Nav2、RTAB、OpenVINS 和局部跟随仍保留已有 ROS/原生库机制，不合并为一个 Python 进程。

当前具体协议与例外以
[接口登记](../../interfaces/registry.json)、
[模块清单](../../platform/modules.json) 和
[已落地架构自审](../../docs/architecture/PLATFORM_IMPLEMENTATION_REVIEW.md) 为准。

### 1.3 已有验证，不重复迁移

此前已有：五模块独立环境与安装检查、结果契约、ROS 类型/依赖 DAG、
默认本机组合与生命周期、真实 Nav2 的模拟输入集成、所选 OpenVINS/RTAB 构建。
最近软件流程基线见 validation/cpu-flow/release-manifest.json：
真实 CPU Voice→BT→Action 链路与模拟导航、推理中停止/重启、旧会话迟到结果隔离已验证。
Qwen SIT 被既有 Lite3 门限拒绝，词库 GO_HOME 导航成功；二者不能合称实机动作成功。

两套整机开发 profile 的感知仍默认 mock；真实 CPU 感知属于独立可选路径。
模型失败记录保留，当前不继续做精度优化。
没有硬件、真实传感器、真实板端性能或 hosted CI 验收。

## 2. Major Problems — 本轮关闭与外部待办

主仓散落、日常命令分散、活动工具默认依赖旧目录、缺少真实源码交付验收等问题，
已由开发 CLI、开发文档、CI 命令复用、显式归档路径和独立克隆验证处理。
审查发现的 Vision workflow 重复 run 键已修正；全部工作流经过重复键拒绝和 shell 语法检查。
本地通过不代表 hosted CI 已上线。

当前未完成项：
1. remote URL、访问范围、真实 owner 和 runner 未提供，不能配置真实远端治理。
2. 板端 OS/ABI/厂商 runtime 未知，不能把 WSL 环境和二进制当作板端部署产物。
3. 实际 Lite3、传感器和模型质量验收仍独立保留；本阶段不做精度优化。
4. 部分第三方/厂商资料对外分发许可未知，当前只做本地内部源码交付。

## 3. Target Architecture

目标是 **一个自研主仓、多个可独立开发的领域包、稳定的公开契约、独立环境、
统一开发命令和可组合运行配置**。不建立业务大 common、全局 RobotState 服务或新的总控总线。

~~~text
marsdog-platform/
  modules/{vision,voice,emotion,behavior,action}/
  robotics/ros2/src/                 # 自研 ROS + waypoint
  interfaces/                       # IDL、契约登记、外部边界
  config/                           # 已验证 profile 与开发配置
  platform/                         # 模块/构建清单、独立构建工具
  third_party/                      # 固定来源/哈希/许可记录
  tools/                            # 开发、构建、集成与交付工具
  integration/                      # 契约、流程与平台工具测试
  docs/                             # 开发、架构、交付及历史
  validation/                       # 已冻结的验收证据
  .github/                          # CI、PR 模板、owner 规则
  .external/                        # 忽略：重建的 vendor 源码
  out/                              # 忽略：报告、构建和本机输出
~~~

一个跨模块需求在同一个分支/PR 中提交生产方、消费方、配置和契约测试。
模块目录统一不等于依赖环境、运行进程和硬件配置统一。

## 4. Module Boundaries

| 模块 | 拥有 | 不拥有 |
| --- | --- | --- |
| Vision | 观测、目标生命周期、推理、视觉任务 | 行为优先级、执行机器人动作 |
| Voice | 唤醒/会话、ASR/意图、语音任务/事件 | 全局仲裁、底盘控制 |
| Emotion/Needs | 唯一领域状态与需求结算 | Action 调度、导航与共享总状态 |
| BehaviorTree | 候选选择、仲裁、抢占、会话协调、结果业务映射 | 推理内部实现、执行阶段和运控 |
| Action | 技能阶段、取消/终态、外部能力适配与已有局部控制 | 第二套全局决策或需求结算 |
| Navigation/ROS | 定位/建图/规划/跟随/避障能力 | 对话与情绪业务策略 |
| 工程工具 | 组合、构建、测试、证据和交付 | 在线业务决策和状态权威 |

保持现有 Vision←Emotion 策略反馈；通信反馈环不是源码依赖环。
Nav2 内部 BT 与 MarsDog 全局 BT 不混同。未知生产用途的旧入口继续保留。

## 5. Dependency Rules

- 禁止跨模块导入私有实现；允许已登记的 ROS generated srv/action 类型依赖。
- Python import 与 ROS package 构建图必须无环。业务通信反馈另行描述。
- 每模块只使用自己的 pyproject.toml、uv.lock、.venv；集成通过独立进程协调。
- 不通过 sys.path、共享大环境或历史仓绝对路径掩盖缺依赖。
- 新依赖只改变所属模块锁；不借平台整合升级算法、ROS、模型 runtime。
- 同名概念先核对现有定义；有两个真实消费者与稳定语义再评估小型公共库。
- 新功能先确定领域 owner、契约生产者/消费者和取消/失败语义，再写实现。
- 历史兼容例外在 platform/modules.json 登记，不在本轮随意消除。

本轮新增 dev.py 是工程包装层，复用原测试/安装机制，不成为模块运行依赖。

## 6. Interface Strategy

稳定已有 ROS 包名、类型身份、端点、字段、QoS、取消/终态与需求结算。
公共 marsdog_interfaces 已提供并迁入；v1 的“该包缺失”结论已过时。
VoiceTask/VisionTask 继续由原 owning package 定义；
waypoint 借用 VoiceTask 的现状已记录，不借本次开发体验改动替换协议。

现有接口 registry、IDL 指纹和 Action→BT→Needs 契约检查继续生效。
新接口必须有生产方、消费方与兼容样例；不把业务阈值或仲裁规则放接口公共目录。
未来运动/嵌入式只按已有外部调用要求保留边界，未知协议不臆造。

## 7. Python Environment Strategy

统一工具和命令，保留模块独立锁文件；**当前不适合一个根 lockfile/虚拟环境**。

- 支持基线：Ubuntu 22.04 / Python 3.10 / ROS Humble。
- Emotion/BT 的 ROS 可选依赖使用 NumPy 1.26.4。
- Action 当前使用 NumPy 2.2.6。
- Voice/Vision 使用 NumPy 1.x，且有不同推理/音频/视觉依赖。
- Voice 可选 intent-cpu extra 保留 Torch/Transformers；原 RKLLM 仍存在。
- Vision 的 RKNN/RGA、Voice RKLLM/设备库及板端 SDK 有自己的 ABI/runtime 要求。
- ROS 构建工具使用 platform/humble-build-tools 的独立环境。

本轮开发入口：

~~~bash
python3 tools/dev.py info
python3 tools/dev.py check
python3 tools/dev.py setup emotion --uv /absolute/path/to/uv
python3 tools/dev.py test emotion
python3 tools/dev.py test voice --ros
~~~

setup 一次同步一个模块，使用 --locked，不自动重解依赖。
Voice 环境若需 CPU 意图，setup 必须带 --intent-cpu；
整机 prepare 必须带 --voice-intent-cpu，否则可选依赖可能被同步移除。
完整使用说明见 [快速开始](../../docs/development/QUICKSTART.md)。

## 8. ROS Workspace Strategy

自研 ROS 包继续位于 robotics/ros2/src；模块 ROS 入口/IDL 身份保持。
tools/marsdog.py 是已有统一本机 prepare/build/doctor/up/smoke 入口，
platform/ros-build.json 登记构建选择；out 保存 build/install/log，不污染源码。

- lite3-local-cpu：感知 mock、模拟导航/设备，隔离 domain 210。
- lite3-nav2-cpu：真实 Nav2，模拟地图/定位/运动/设备，domain 212。
- 两者均不代表 Lite3 实机发布，不自动放开未验证动作。
- 同域流程验收不并行运行；源码改动按指纹要求重建。
- 原 robot_ws/rtabmap_ws 不再是新功能开发目录，保留为来源档案。
- 本机固定 x86_64 依赖不自动推广为开发板依赖。

当前活动工具归档查找优先级为：
显式 --archive-dir → MARSDOG_ARCHIVE_DIR → 本仓 .cache/vendor-archives。
历史 migration 工具的旧 workspace 参数仍只服务旧基线核对。

## 9. Third-party / RTAB-Map Strategy

third_party/sources.lock.json 固定四个 vendor 的完整 commit/tree 与归档哈希。
RTAB 保留整个本地 fork，不能用最新上游替换；OpenVINS 的定制融合也保留。
完整上游 delta、部分厂商库来源/许可仍 UNKNOWN，已有来源记录不丢失。

所需内部源码归档包括：

- robot-7dd357f-all-refs.bundle：OpenVINS、VINS、UWB 的锁定来源。
- rtabmap-91faa21-all-refs.bundle：RTAB 完整锁定来源。

当前归档位置 /home/elephant/MarsDog/migration/archives 可以显式复用，
但新克隆不得靠旁边存在原源码仓才能运行。materialize_vendors 校验哈希和树后生成 .external。
RTAB 生成源码文件的构建副本继续放 out，不放宽 sealed snapshot 校验。
模型、厂商制品和许可证作为独立资产问题处理，不为了交付打包而公开分发。

## 10. Git History Migration Strategy

主要历史迁移已经完成，**不重新 filter、reset 或导入原仓**。
原仓、原始 bundle、commit maps 均保留；主仓导入后的 SHA 与原 SHA 映射按记录解释。

已实现并验证 tools/source_handoff.py：
要求主仓 clean，通过 git bundle --all 导出历史并登记 refs/commit/哈希；
可显式附带两份锁定 vendor bundle，拒绝覆盖已有输出目录。
该工具的真实 Git 往返/破坏校验与实际主仓导出、独立克隆均已通过。
源码验收基线 2468639，证据见 validation/developer-platform。

不纳入主仓或源码包的工作数据：
.venv、build/install/log、.external、模型、缓存、录音/人脸/声纹/地图数据库、
私有设备配置与凭据。原历史中已保留内容不在本轮改写删除。
源码包不是离线依赖镜像，不承诺首次安装无需网络。

## 11. Testing Strategy

三级验证分开报告：

1. 模块/平台：标准库架构检查、独立模块单测、干净 wheel 安装、契约。
2. 软件集成：已有 Humble/IDL、隔离 DDS、进程启停、默认与 Nav2 模拟 I/O profile。
3. 板端/设备：实际 ABI/runtime、传感器、Lite3、性能与停止语义；当前未执行。

本轮 dev.py test 保留实际 counts/skip reasons；
Voice 默认纯子集明确排除 ROS 文件，--ros 才是完整 Humble 单测。
Vision 完整单测依赖 Humble；RGA 缺设备跳过须保留。Action 既有跳过不算通过项。

既有最近基线：Voice 430/0 skip、平台 39、结果契约 25；
本轮新增工具回归后平台为 51。不同阶段的数字不可混称本轮全部复跑。
其他模块历史计数见 STATUS 与冻结报告，不盲目加总 subtests/CTest/JUnit。

## 12. CI Strategy

保留模块独立 jobs，不建立根大环境。
已修改 workflow 复用 dev.py setup/test/check，减少本地与 CI 命令漂移；
本轮完成 YAML 重复键检查、shell 语法验证及本地对应命令验收。
干净 wheel 检查保留；Vision 的普通 hosted job 不冒充 Humble 全量单测。
ROS/扩展构建仅在明确配置的 localhost 专用 runner 手动触发。

目前无 remote、真实 CODEOWNERS 账号或 hosted CI 运行。
角色定义见 docs/OWNERSHIP.md；不伪造账号，不私自选择对外仓库。
新增 PR 模板说明行为、兼容性、生产/消费双方、命令与未覆盖项。
在缺远端阶段完成本地相同命令验证即可，但诚实保留外部配置未完成。

## 13. Migration Phases

| 阶段 | 当前状态 | 接下来 |
| --- | --- | --- |
| P0/P1 架构、原始基线、契约 | 已完成 | 保留来源与证据 |
| P2–P4 五模块历史/包/接口迁移 | 已完成 | 在主仓做普通功能开发，不再搬迁 |
| P5 自研 ROS + 接口/航点 + vendor | 软件迁移与所选 CPU 构建完成 | 按实际需求验证更多配置，设备项另列 |
| P6 WSL 本机组合与流程 | 默认组合、真实 Nav2 模拟输入、CPU Voice 流程已有证据 | 保留为跨模块回归基线 |
| P7a 团队开发入口 | **完成；2468639** | 五模块新入口、CI 本地等价命令、独立安装已验证 |
| P7b 独立克隆与源码交付 | **完成；validation/developer-platform** | 实际 bundle/独立克隆、五环境、四 vendor、默认 ROS 从零构建与 smoke 通过 |
| P7c 团队远端治理 | 外部信息未配置 | URL/owner 确定后配置权限、CI/保护分支 |
| P8 开发板/Lite3 | 无设备与板端环境 | 板端事实确认后单独构建、逐步接入 |
| 旧代码退役 | 不在当前必做范围 | 用途证据及确认后单独处理 |

本轮软件阶段完成标准是：一份可独立克隆的主仓，新成员按文档可测试模块，
同一 PR 可修改生产/消费双方并跑门禁，WSL 可统一启动，交付能追溯源码与外部资产。
**无需等待实机或模型精度达标；也不能声称硬件阶段已完成。**

## 14. Risks and Architecture Review

### 最大五个风险

1. 新会话误读 v1/历史交接而重新迁移或重新调模型：以本文和 Git 实际状态为准。
2. 文档/CLI 声称独立但依赖原仓、环境污染或漏测试：干净检出与独立环境真实验证。
3. 模型/ROS/NumPy/板端 ABI 强行统一：保留独立锁，板端重建，不复制 WSL 环境。
4. 忽略取消、结果结算与 Lite3 门限：持续原契约，任何可见行为变更单独确认。
5. 历史/vendor 定制或分发边界丢失：保全归档/映射、校验来源，不擅自公开发布。

### 本轮自审

- 没有新增在线业务中心；dev.py 和 source_handoff.py 只用于工程流程。
- 没有将 Emotion/Needs、仲裁或阈值放 common；模块依赖 DAG 沿用。
- 不因合仓改变 ROS 包身份或强制共享依赖环境。
- 第三方保持来源隔离，没有当作自研算法重写。
- 所有功能在同一主仓提交，契约/集成与代码同 PR，减少跨仓人工协调。
- 不新增复杂插件框架、自动影响分析服务或板端虚假 ready 状态。
- 已验证 BT 两棵测试目录、Voice 可选依赖与纯/Humble 范围、跳过原因、失败退出和归档路径。

## 15. Current Migration Slice — 已完成与后续使用

### 15.1 本轮完成

代码提交：2468639054763398882366bad7869236c0d2e68e。
验收在 2026-09-29 UTC 执行，文档/交接于 2026-09-30 收尾；
完整证据位于 validation/developer-platform，旧验证快照保持不变。

- 保全并审查原有 25 个未提交工程文件；修复 Vision CI 重复 run 键。
- 开发 CLI 保留单模块锁/环境、BT 双测试目录、Voice extras、纯/Humble 区分与 skip 报告。
- 原环境和干净克隆均通过架构/51 项平台测试与 25 项结果契约。
- 两处模块测试结果一致：Emotion 218 tests + 156 subtests、BT 533、
  Action 423 pass / 29 skip、Voice pure 253（明确排除 5 文件）、
  Voice Humble 430 / 0 skip、Vision 289 pass / 3 RGA skip。
- 干净克隆通过五模块独立 setup 和五个干净 wheel 安装检查。
- 实际源码 bundle 校验 commit/refs/哈希，附两个锁定 vendor bundle；
  新克隆重建 OpenVINS、VINS、UWB、RTAB 四个固定源码树。
- 原 WSL 的显式归档 prepare（保留 Voice CPU extra）、doctor、默认 smoke、
  中断/崩溃传播/重复启动与 PID 回收门禁通过。
- 新克隆在已有 Humble 主机上从零构建默认组合 15 包，并通过 doctor/smoke；
  没有复制旧 .venv、build/install，没有重编本轮不涉及的 SLAM 扩展。

Emotion 的 374 JUnit entries 包含 156 subtests，不能另算为 374 个顶层测试。
Voice pure/Humble、契约/接口检查存在覆盖重叠，不加总为独立功能数。
Action 29 skip 为 20 个 ROS 依赖项和 9 个 PySide2 GUI 项；Vision 3 项需要 RGA 设备。
总体验收为 PASS_WITH_EXPLICIT_LIMITS，不代表模型精度、实机或 hosted CI 通过。

### 15.2 交付与新成员入口

源码验收包：out/handoff/source-bundle-2468639。
最终源码包：out/handoff/source-bundle-final，包含验收证据及最新交接；
源码内容与验收提交保持一致，文档/证据的提交号以包内 manifest 为准。
两包均为内部本地交付，包含历史与固定 vendor 归档，不包含环境、模型或构建目录。

在本仓根目录使用：

~~~bash
python3 tools/dev.py info
python3 tools/dev.py check
python3 tools/dev.py setup emotion --uv /absolute/path/to/uv
python3 tools/dev.py test emotion
python3 tools/dev.py test behavior
python3 tools/dev.py test action
python3 tools/dev.py test voice
python3 tools/dev.py test voice --ros
python3 tools/dev.py test vision
python3 tools/check_contracts.py
~~~

具体准备、命令范围和安装门禁见 docs/development/QUICKSTART.md。
交付包复制后先 verify，再 clone；完整命令见 docs/deployment/SOURCE_HANDOFF.md。
可显式共享下载缓存；运行时不通过旧源码目录补 import。
原 WSL Voice 含 CPU extra，后续同步需继续显式选 --intent-cpu / --voice-intent-cpu。

### 15.3 后续边界

本阶段软件目标已经完成，按真实功能需求在主仓继续开发即可。
不要重做合仓，不继续无目标的 SLAM 全量重编或模型精度优化。
remote/owner/runner 确定后再配置 PR、CODEOWNERS、保护分支和 hosted CI。
取得板端及真实设备事实后单独构建并逐步接入；不能复制 WSL 二进制冒充板端成果。
未知协议、明显行为变化、不可恢复删除和对外分发仍按第 16 节处理。

### 15.4 当前新切片：五模块兼容性重构

用户于 2026-09-30 授权整合 Voice、Vision、Emotion、BT 和 Action，
前提是不影响原始功能；导航/避障内部实现暂不处理，后续由负责人修改。

路线与边界见 docs/architecture/COMPATIBILITY_REFACTOR.md。先冻结跨模块契约，
再提取无状态协议处理，最后按职责分步拆分节点；不创建承载业务的 common，
不强行合并 Python 依赖或 ROS 类型，不做模型精度优化。

R1–R4 已全部完成：audio v2、visual v1、state v2、任务服务和 ExecuteBehavior
形成统一应用协议目录；Voice 会话/识别/任务、Vision 快照/事件/任务、Emotion 发布、
BT 状态/视觉/语音协调、Action 生命周期/执行/消息构造均按领域拆出，旧方法入口保留。

声音 46、视觉 33、状态 34、任务每端 18、原结果 25 契约全部与冻结行为一致；
五模块全量回归、平台 71 项、五个独立 wheel 与 18 个组件安装哈希检查通过。
当前安装的默认 ROS 15 包增量构建、doctor/smoke、35 项真实动作回调、DDS 取消 ACK
到终态的归属保持、SIGINT/SIGTERM 停止后退出以及 supervisor 故障清理均通过。
源码 AST 等价与 286 个配置/锁/IDL/模型适配器/导航等保护文件字节一致性已核实。

本轮证据见 validation/compat-refactor/r2-r4；R1 与 P7 历史证据保持原样。
完成的是授权的软件兼容性重构范围，不宣称所有算法重写、模型/实机或远端 CI 验收。
P7 源码包仍对应原验收提交，不包含本轮新增源码。

## 16. Human Confirmation and External Inputs

无需再次询问普通目录、CLI、测试、文档、兼容性修复或本地提交。
需要事实或重大决策时才确认：

- remote URL、访问/公开范围、真实 owner/团队账号；
- 开发板型号、CPU ABI、OS、Python/ROS、NPU/SDK 版本；
- 实际 Lite3、传感器/地图/标定和对应验收环境；
- 厂商/第三方资料能否对外分发；
- 不兼容协议、明显行为变化、未知生产代码退役、不可恢复历史/数据删除；
- 缺失运动/嵌入式协议的新定义或大规模算法重写。

外部信息未知只阻塞相关发布/设备步骤，不阻塞已授权的软件工作。
保持原仓只读、不删除档案、不改已冻结的旧验证结论。

## 17. 文档与历史依据

本文件 v1 原文保存在聚合目录的
ARCHITECTURE_AND_MIGRATION_PROPOSAL.20260928.v1.md；
主仓旧版本也可通过以下只读命令恢复查看：

~~~bash
git show 3bf529e:docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md
~~~

v1 保留七仓原始 HEAD、源码依据 B01–B16 与最初决策。其“尚未迁移/接口缺失”
措辞属于历史，不是当前待办。
本文在用户指定的聚合目录与主仓 docs/architecture 下同步维护，
后续执行以主仓 Git 实际内容和最新 STATUS 为准。

其他入口：
[源码交付](../../docs/deployment/SOURCE_HANDOFF.md)、
[CPU 软件流程](../../docs/CPU_SOFTWARE_FLOW.md)、
[默认本机](../../docs/LOCAL_LITE3_CPU.md)、
[Nav2 本机](../../docs/LOCAL_NAV2_CPU.md)。
