# MarsDog Architecture and Migration Proposal

**版本：2.0 · 更新：2026-09-29 · 状态：主仓迁移已落地，正在完成团队开发与源码交付闭环。**

本文是后续会话的执行计划，替代 v1 中“尚未实施、下一步 P1”的进度判断。
用户的最终目标是：把多个模块仓库整合为一个长期可维护的主仓，统一架构和工程入口，
使新功能开发、提交合并、新成员上手与整机集成都更容易；先在 WSL2 整理和验证，
后续再到开发板构建、接入 Lite3。**当前没有真实硬件，模型精度暂不作为本阶段阻塞条件。**

普通工程决策和必要实现已授权，不需要逐项确认。不要重新合仓、重新设计大框架，
也不要把工作重新收敛到提示词、准确率或缺失硬件的调试。
用户自行创建后续会话；执行者不需要创建、发送或管理其他会话。

## 0. 新会话先读：事实、当前位置和第一步

实际开发仓库在 WSL 的：

~~~text
/home/elephant/MarsDog/marsdog-platform
~~~

Windows 客户端可能显示 C:\home\elephant\MarsDog，这不是当前实际 Linux 源码位置。
WSL 发行版 Ubuntu-22.04；项目挂载路径可为：
\\wsl.localhost\Ubuntu-22.04\home\elephant\MarsDog。

本文件位于聚合目录，不意味着聚合目录本身是 Git 主仓。
唯一新增业务开发位置是 marsdog-platform，不能在聚合目录再初始化第二个主仓。

交接时已提交基线：**main / 3bf529e**，之前源码修复提交 f102172。
本轮有**尚未提交**的开发体验、CI、源码交付工具和文档修改；保留并复核，不覆盖或重做。
截至本文更新，已实际运行 `python3 -B tools/dev.py check`：
架构检查通过，平台 **51 tests / OK**。日志：
`marsdog-platform/out/developer-platform/dev-check-initial.log`。
这只证明当前工具/架构门禁通过，**尚未验证新 CLI 的所有模块真实执行、完整干净克隆或实际交付包**。

新会话立即执行：

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
git status --short
git log -3 --oneline
git diff --stat
python3 -B tools/dev.py check
~~~

然后按第 15 节完成当前切片。先读：
[AGENTS](../../AGENTS.md)、
[贡献指南](../../CONTRIBUTING.md)、
[当前状态](../../docs/migration/STATUS.md)、
[开发流程](../../docs/development/WORKFLOW.md)。

历史证据在 validation/*；本文中“此前通过”不等于本轮重新运行。
后续任何更新都应写清来源 commit、命令、执行环境、PASS/FAIL/SKIP/UNKNOWN 和证据位置。

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

## 2. Major Problems

当前主要问题已从“源码散落七仓”转为“主仓是否真正便于开发和交付”：

1. 旧 README/交接长期堆积迁移与模型实验记录，新成员难以辨认日常入口。
2. 本地测试与 CI 命令分散，易漏 BT 的第二测试目录或误把 Voice 纯子集算全量。
3. 部分活动工具默认查主仓旁的 migration/archives，降低克隆后的独立性。
4. 缺少可验证的源码交付流程，容易把 WSL .venv/build/install 当板端部署产物。
5. 没有真实 remote、owner 身份和 runner；CI 文件存在不能被当作已上线。
6. 板端 OS/ABI/厂商 runtime 未知；合并 Python 环境或直接复制 x86 二进制会制造问题。

本轮已经写入对应工具/文档修订，仍需执行验证和提交，见第 15 节。

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

本轮新增 tools/source_handoff.py：
要求主仓 clean，通过 git bundle --all 导出历史并登记 refs/commit/哈希；
可显式附带两份锁定 vendor bundle，拒绝覆盖已有输出目录。
这项工具目前通过小型真实 Git 往返与破坏校验测试，
**实际主仓导出/独立克隆尚待执行，不能提前标完成**。

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
本轮修改 workflow 复用 dev.py setup/test/check，减少本地与 CI 命令漂移。
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
| P7a 团队开发入口 | **本轮实现中，未提交** | 审查新 CLI/文档/CI、运行真实模块门禁 |
| P7b 独立克隆与源码交付 | **工具已写，实际交付待验证** | 干净历史 bundle、独立环境和固定 vendor 验证 |
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
- 本轮仍需检查工程包装是否遗漏原测试/环境选项，不能只看新增测试数。

## 15. Current Migration Slice — 新会话按此执行

### 15.1 本轮已写入，尚未提交

- tools/dev.py：info/check/setup/test；platform/modules.json 增加 development recipes。
- tools/source_handoff.py：历史 bundle 导出/哈希/refs 校验，可附固定 vendor 归档。
- tools/runtime_environment.py、marsdog.py、materialize_vendors.py、
  check_extended_ros_build.py：显式归档路径与本仓默认缓存，移除活动工具的隐式旧目录依赖。
- integration/platform/tests/test_developer_workflow.py、test_source_handoff.py：
  锁/单模块/双测试目录/skip 报告/环境隔离，真实 Git 往返/脏仓拒绝/篡改拒绝等。
- README、CONTRIBUTING、AGENTS、docs/development、docs/deployment、PR 模板与六个 workflow。
- 本文、主仓方案副本、STATUS、HANDOFF 的进度与目标更新。

git status 是完整清单的权威。当前未改业务模块、五套锁、公开 IDL、生产 YAML 或默认 profile。
若新会话发现其他改动，先辨认来源，不覆盖。

### 15.2 实施与验收顺序

1. 阅读 diff 与新增文件，确认包装命令与原脚本等价；
   特别检查 BT 两棵测试目录、Voice extras、skip 计数、归档参数和失败退出。
2. 用新入口实际执行受影响的模块测试。已有主仓环境可复用，
   不为验证 setup 而把带 CPU extra 的 Voice 环境意外同步掉。
3. 验证 CI YAML 和本地同命令；按需验证干净 wheel/install。
   未改模块源码/IDL不要求无理由全量重编所有 SLAM，但所有变更涉及的路径须验证。
4. 审查并提交当前切片，得到干净、可追溯的源码 commit。不得导出 dirty 工作树当正式源码包。
5. 导出实际主仓 bundle（附显式 vendor archive-dir），验证，再克隆到全新位置。
   克隆位置不能靠旧源码目录补 import；可以明确共享下载缓存。
6. 在新克隆运行 dev.py check，至少完成 Emotion/BT/Action 独立 setup/test 和结果契约；
   验证固定 vendor materialize。按实际资源条件扩大五模块安装及本机 prepare/build/smoke。
   若完整 fresh ROS 构建未运行，明确写“仅已有构建回归”，不能叫全新安装整机验收。
7. 因本轮改了启动准备相关默认值，在已有 WSL 运行 doctor/默认 smoke，
   验证显式归档路径工作；保留原 runtime 配置、取消与行为门限。
8. 将命令、环境、源码 commit、结果、局限冻结到新的 validation/developer-platform
   （不要覆盖 validation/cpu-flow 等旧快照）；更新 STATUS/HANDOFF 后提交。
9. 最终汇报新成员入口、开发命令、源码交付位置、Git commit、真实验证结果，
   以及 remote/owner/板端等外部待办。完成当前软件目标后不无目的扩大到模型调优。

具体命令参考：

~~~bash
python3 tools/dev.py test emotion
python3 tools/dev.py test behavior
python3 tools/dev.py test action
python3 tools/dev.py test voice
python3 tools/dev.py test voice --ros
python3 tools/dev.py test vision
python3 tools/check_contracts.py

# 审查、完成必要修正并提交之后；输出目录必须不存在
python3 tools/source_handoff.py create --directory out/handoff/source-bundle \
  --archive-dir /home/elephant/MarsDog/migration/archives
python3 tools/source_handoff.py verify --directory out/handoff/source-bundle
git clone /absolute/path/to/marsdog-platform.bundle /new/isolated/marsdog-platform
~~~

这些是后续动作，**截至本次交接尚未全部执行**。
参考当前 uv：/home/elephant/MarsDog/migration/.tools/uv；
缓存：/home/elephant/MarsDog/migration/.cache/uv；
Python：/usr/bin/python3.10；ROS：/opt/ros/humble。
新文档面向普通开发者时用可配置路径，不把当前个人绝对路径写成必要依赖。

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
