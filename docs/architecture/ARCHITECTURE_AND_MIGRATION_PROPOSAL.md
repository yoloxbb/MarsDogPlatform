# MarsDog Architecture and Migration Proposal

**状态：已完成架构自审并修订的提案；尚未实施迁移。**

**版本：1.0 · 日期：2026-09-28 · 角色：Principal Engineer / Technical Lead**

本文件区分「源码事实」「目标决策」「迁移期间的例外」和「待确认事实」。目标路径都是规划，不表示目录、包、接口或 CI 已经创建。本轮只新增本文件；不移动实现，不修改依赖、ROS 接口、机器人行为或原仓库 Git 历史。

## Executive Decision

采用 **MarsDog 自研代码主仓 + 固定版本的第三方源码/制品 + 模块独立 Python 项目 + 分层 ROS 构建**。

主仓统一契约、集成测试、发布清单和开发入口；保留 Vision、Voice、Emotion/Needs、BehaviorTree、Action、Navigation 的模块独立性。现有 Python import namespace、ROS package 名称和外部端点首先保持不变。成熟算法以迁移、包装和验证为主。

不建立统一业务大内核、全局 RobotState 服务、通用事件总线或包含全部依赖的单一虚拟环境。接口集中治理不等于立即把所有 IDL 改名搬进新 ROS package。

最先交付“可重复的兼容性基线与跨模块回归检查”，第一个实现迁移选择 Emotion/Needs。BT 与 Action 随后成对验证、分步迁移。硬件推理及 SLAM 第三方算法最后处理。

## 1. Current Architecture

### 1.1 事实基线

本提案以第一阶段源码分析为基础，并重新核验以下七个 HEAD。复核时工作树均为 clean。没有进行硬件运行、ROS 构建或全量测试；本文件不能被当作运行验收报告。

| Source ID | 现有仓库 | 固定基线 commit |
| --- | --- | --- |
| vision | MarsDog | a05dbf4b9cf3cde9707f05c4360d39e5a52968df |
| voice | MarsDogVoiceInteraction | df85e30509b9561d782c1963e3ff362d39cbfa14 |
| emotion | MarsDogEmotion | cd1e0476df7ab20873d048a8508e67301e7231c1 |
| behavior | 20260702_MarsDogTree | 9f2eb0dee84f84bb84a4e497aba4e3effe4d10da |
| action | 20260707_MarsDogAction | f00c3fdf2945c7a09d5f49ffc3d0df39c37ca2a8 |
| robot | slam/robot_ws | 7dd357fdfe1664775c051195a3c0562af6892d84 |
| rtabmap | slam/rtabmap_ws | 91faa212039c9274f67aa30c147eeb4dfbfc63f2 |

当前聚合目录本身未发现 Git 仓库。它不能直接当作已经存在的新主仓，也不应在其上直接初始化 Git 并将七个嵌套仓库作为普通目录提交。

### 1.2 已证实的运行关系

~~~mermaid
flowchart TD
    V[Vision] -->|visual_event| B[BehaviorTree]
    W[Voice] -->|audio_event| B
    V --> E[Emotion / Needs]
    W --> E
    T[时间 / 人格 / 触摸] --> E
    E -->|state / signal_event| B
    E -->|emotion/state| V
    B -->|VisionTask / VoiceTask| Q[感知能力与语音会话服务]
    Q --> V
    Q --> W
    B -->|ExecuteBehavior| A[Action]
    A -->|feedback / result| B
    B -->|需求相关 result_event| E
    V -->|目标与物体事件| A
    A --> N[Nav2 / 人员接近 / UWB]
    A --> X[Go2 / Lite3 外部执行端]
    A --> U[航点服务：本地未找到服务端]
~~~

上图 Q 只是服务关系的归类，不是实际存在的中心服务进程。

主要源码依据见附录 B01—B16：

- Vision/Voice 发布 JSON over ROS String，兼有各自的 task service。
- Emotion/Needs 依据感知、时间、人格、触摸和行为结果计算状态；BT 使用其状态和信号。
- BT 负责候选行为、仲裁、抢占、会话参与和结果业务映射。
- Action 负责行为内部阶段、设备适配、导航/跟随调用，还包含视觉接近等速度级闭环。
- Action 未实现已知的关节级运控算法。外部运控、嵌入式和 BMS 内部行为为 UNKNOWN。
- Mapping 主要由 RTAB 承担；Navigation 使用 Nav2 配置/插件；UWB Following 和局部避障有自己的节点链。
- OpenVINS 可以作为 RTAB 进程内库，不应无条件画成独立 ROS 进程。

### 1.3 必须保留的现有行为

- 视觉目标由 vision_epoch 与 target_id 等字段识别，不能退化成仅凭姓名锁定。
- “cancel 已接受”不等于执行已终止；现有 BT/Action/航点代码已处理这一差别。
- BT 才是需求相关 /behavior/result_event 的主要生产者；不是每个动作都产生需求结算。
- Emotion 当前存在中断行为对需求的特定结算规则，必须按现有测试保留，不能统一改成“只有成功才改变需求”。
- 陌生人策略受 Emotion 影响的反馈环当前存在，迁移不能直接删除。
- 部分 Action 控制器和导航默认关闭；不能为了集成演示自动开启。
- Action 充电结果电量目前来自配置参数，默认 100。它是现状，不是真实 BMS 观测。

### 1.4 尚未证实的运行事实

生产机器使用的 launch/参数/overlay、模型版本、真实执行器接口来源、航点服务位置、速度控制最终消费端及真实硬件停止语义均为 UNKNOWN。源代码支持某能力不等于该能力已经部署。

## 2. Major Problems

| 问题 | 具体事实 | 对迁移的影响 |
| --- | --- | --- |
| 协议来源漂移 | BT 依赖 marsdog_interfaces，本地缺失；BT/Action 都有优先导入它的逻辑 | 单纯新增同名接口包可能改变运行类型选择 |
| 隐式契约 | JSON 字段、事件名、行为名、动作 ID、frame/QoS 分散在多个仓库 | 跨模块改动缺少自动影响分析 |
| 环境冲突 | Vision/Voice 要求 NumPy <2；Action 要求 >=2.2.6；pytest 也冲突 | 不适合一个全局 uv workspace/lock/environment |
| 启动与构建不闭合 | robot_ws 构建/加载脚本遗漏 go2_follow_ws；默认 RTAB 目录名不匹配 | 目录统一后仍可能无法集成 |
| 原生依赖双向可见 | robot 启动 RTAB；RTAB 又链接 robot 内定制 OpenVINS | 要拆清构建 DAG，不能用 source_all 掩盖 |
| 能力与实现不齐 | 航点服务端缺失；部分 manipulation 路由没有真实适配器 | 集成测试要显式报缺能力，不能成功模拟冒充实机 |
| 速度路径重叠 | Nav2、UWB、Action 直接视觉接近均能影响运动 | 需要验明既有控制权/停止边界；不能未经确认重写运动路径 |
| 生产依赖不完整 | 模型、设备、部分 ROS 类型、硬件端不在当前树 | 软件可构建与硬件可运行必须分开验收 |
| 第三方来源混杂 | RTAB/OpenVINS/VINS 和项目集成一起维护 | 算法升级和项目修改难以分辨 |
| 历史代码状态未知 | legacy launch、mock、旧入口仍在 | 不能按命名直接删除或停用 |

迁移必须记录已有缺陷，不能为了宣称“迁移无回归”将它们掩盖，也不能借迁移顺手改变已有产品行为。

## 3. Target Architecture

### 3.1 主仓职责

规划主仓名为 **marsdog-platform**。本轮不创建该仓库，不选定远端 URL，不更改当前聚合目录。

规划布局如下；这是责任分区，不要求一次性建全空目录：

~~~text
marsdog-platform/
  modules/
    vision/                    # 原视觉项目；保留现有包名与内部目录
    voice/                     # 原语音项目
    emotion/                   # 原 Emotion/Needs；先保留 core + ROS wrapper
    behavior/                  # 原 BT；保留 bionic_dog_bt / marsdog_behavior
    action/                    # 原 Action；保留 executor 和现有适配器
    navigation/
      robot_slam_bringup/
      stereo_slam_legacy_bringup/
      person_3d_localization/
      behavior_ext_plugins/
      go2_uwb_local_follow/
      go2_uwb_behavior/
    sensors/
      stereo_v4l2_camera/
      wit_imu/
  contracts/
    registry.yaml              # 端点、类型、owner、消费者、IDL 原位置、版本
    schemas/                   # 已存在 JSON 协议的描述，按领域组织
    fixtures/                  # 无个人数据的兼容样例
    external/                  # 现有底盘/BMS/设备边界与 UNKNOWN
  integration/
    marsdog_bringup/            # 集成 launch；不包含决策或算法
    profiles/                  # 模拟/Go2/Lite3 等经过验证的组合
    scenarios/                 # 跨进程回放与集成验收
  platform/
    modules.yaml               # 模块、命令、依赖、owner 角色、测试标签
    python-toolchain.toml      # 工具版本与支持矩阵，不是全局依赖合并
    ros-build.yaml             # 明确的构建层级和包选择
    artifacts.lock.yaml        # 模型/厂商库/标定制品的哈希和来源
  third_party/
    sources.repos              # 固定到完整 commit 的获取清单
    provenance/                # 上游基线、项目改动、许可证与升级记录
  tools/                       # 少量显式 build/test/doctor 包装命令
  tests/contracts/
  tests/integration/
  docs/architecture/
  docs/migration/
  docs/modules/
  .github/workflows/
  .github/CODEOWNERS
  AGENTS.md
~~~

实际下载的第三方源码进入被 Git 忽略的 .external/；构建输出进入 out/；运行数据位于部署配置指定的外部数据目录。它们不作为自研源码提交。

清单各有唯一职责：modules.yaml 只登记模块入口/owner/测试标签；contracts registry 登记通信契约；sources.repos 登记 vendor 来源；artifacts lock 登记非源码制品；ros-build 只表达 profile 选择和构建层级。它们引用 package.xml/pyproject/IDL，不手工重复完整依赖列表。包依赖图、契约消费者影响图和 release manifest 从这些来源生成并交叉校验，避免多份手工清单再次漂移。

### 3.2 每个旧仓库的去向

| 原仓库/子树 | 主仓目标或外部目标 | 首次迁移原则 |
| --- | --- | --- |
| MarsDog | modules/vision | 原包、测试、配置、launch 原样迁入；不同时切换推理后端 |
| MarsDogVoiceInteraction | modules/voice | 原包与测试迁入；原生库单独成为固定制品，完成等价加载验证后切换路径 |
| MarsDogEmotion | modules/emotion | 第一个实现迁移；原 Python namespace、ROS package、参数和状态协议保持 |
| 20260702_MarsDogTree | modules/behavior | 保留 bionic_dog_bt 与 marsdog_behavior；不重写树 |
| 20260707_MarsDogAction | modules/action | 保留阶段执行和硬件适配器；不随搬迁新增总运动仲裁器 |
| robot_ws/sensor_ws 的项目驱动 | modules/sensors 下原 ROS 包 | 逐包核对来源/许可证，保留可执行名 |
| robot_ws/slam_ws | modules/navigation 下原 ROS 包 | legacy 入口一起保留，不认定其废弃 |
| robot_ws/go2_follow_ws 中 local_follow/behavior | modules/navigation 下原 ROS 包 | 行为和局部规划仍独立 ROS package，不并入高层 BT |
| robot_ws/go2_follow_ws/src/uwb | .external/uwb_aoa，经 third_party 清单固定 | 串口包含厂商静态库；保留现有包与协议，先按 vendor 来源隔离 |
| robot_ws/openvins_ws | .external/openvins-marsdog，受控 fork/快照 | 保留定制腿部速度 API 与完整来源，不改写算法 |
| robot_ws/VINS-Fusion-ROS2-humble-arm | .external/vins-fusion-marsdog | 保留本地改动、词典和运行组合；不用上游最新版直接替换 |
| robot_ws/scripts 与各 workspace README | 有效构建知识进入 platform/tools/docs；旧脚本保留在历史及过渡入口 | 一条命令一个验收，再退役旧入口 |
| rtabmap_ws | .external/rtabmap-marsdog，初期保持整个 vendor 仓库为一个固定单元 | 主仓只管理版本、构建选项、验收和来源 |
| rtabmap_openvins_mono | 初期留在上述 RTAB vendor 单元 | 来源/生产用途未确认，不擅自重归类或删除 |

navigation 下的 package 名称中保留 go2，不立即改成“通用”名字；当前 Lite3 使用这些名字，改名会扩大兼容面。目录名称可表达领域，ROS 类型身份不随目录重命名。

### 3.3 不进入新主仓工作树的内容

- 完整 RTAB-Map、OpenVINS、VINS 上游算法源码，及尚未证明应由主仓维护的 vendor 实现。
- 模型权重、Rockchip/厂商二进制库、UWB 静态算法库：进入有哈希和许可来源的制品或 vendor 管理，不重新提交一份裸二进制到自研模块。
- .git、build、install、log、.venv、缓存和机器生成配置。
- 地图数据库、rosbag、真实人脸/声纹录入、录音、设备凭据和运行日志。
- 原机器用户路径、系统软件和不存在的运控/嵌入式实现。

这不等于删除原仓库里的任何内容。原件与完整历史按第 10 节保留。源码归属不明的部分留在来源隔离区域，直到证据足够再分类。

### 3.4 目标不是一个统一进程

Vision、Voice、BT、Action、Emotion 的 ROS wrapper 可以维持当前进程边界。算法核心可以单独测试；Nav2/RTAB 已有组件和库机制保持。只有性能测量和 ABI/状态隔离验证支持时才考虑改变进程组合，不能以合仓为由合并进程。

## 4. Module Boundaries

| 模块 | 拥有的职责和状态 | 不应拥有 | 对外边界 |
| --- | --- | --- | --- |
| Vision | 视觉观测、目标生命周期、身份/姿态/物体推断、登记 | 行为优先级、底盘执行、声纹真值 | visual/object events、VisionTask |
| Voice | 唤醒、音频/声纹、ASR、语言意图、会话状态 | 执行机器人动作、直接发布速度 | audio events、VoiceTask |
| Emotion/Needs | 需求与情绪权威状态、人格、事件/时间演化、结果结算 | 选择动作、拥有 Action goal、导航 | state/signal events，消费感知与业务结果 |
| BehaviorTree | 跨领域决策、候选仲裁、优先级、抢占、业务交互意图 | 推理模型、SLAM 算法、底盘码、单个技能的低层轨迹 | 感知/状态输入、ExecuteBehavior、业务结果 |
| Action | 单个行为的执行生命周期、阶段、局部控制、取消/终态、适配器 | 第二套全局需求/情绪引擎、重新决定全局行为优先级 | ExecuteBehavior；导航/跟随/运动能力端口 |
| Navigation | 定位、建图、路径/局部规划、人员几何定位、跟随/避障执行能力 | 对话语义、需求结算、全局社会行为选择 | 标准 ROS 数据与现有 Nav2/UWB/定位接口 |
| Sensors | 原始采样、标定、设备协议、健康状态 | 行为逻辑与模型决策 | Image/IMU/UWB 等观测 |
| Bringup/tools | 按配置组合、检查前提、启动、采集验收证据 | 在线业务仲裁、全局状态存储、接管运动 | 组合配置、诊断和开发命令 |

### 4.1 BT 与 Action 的明确界线

BT 决定“现在要完成什么，以及是否抢占”。Action 决定“该目标的阶段如何执行，以及执行是否真的结束”。Action 向外汇报事实；BT 将事实映射成已有的需求业务结果；Emotion/Needs 决定这些结果如何改变自身状态。

保留现有 safe_to_interrupt、cancel accepted 与 terminal result 区分。Action 的局部闭环留在 Action 或其能力提供方，不能因“BT 应统管”而移入树节点。

Nav2 的内部 BT 和 go2_uwb_behavior 的局部模式控制不等于 MarsDog 高层行为树；它们属于技能执行内部机制。

### 4.2 Emotion/Needs 的位置

Emotion/Needs 是独立领域模块，不放进 common，不并入 BT，不作为 Action 的父调度器。保持一个权威计算来源，BT 的镜像/模拟能力明确标注用途。

现有 Vision ← Emotion 反馈属于运行通信环，不是源码导入环。先冻结陌生人策略的输入/输出和事件时序。若未来要把该策略从感知移到 BT，需要产品语义验收；本次不预设迁移。

### 4.3 Navigation 和直接运动的过渡

暂时保留 Action 内的 Go2、Lite3、视觉接近和 UWB 适配器位置。它们向 Action 上层暴露窄的内部能力端口；没有第二个真实消费者时不创建通用 motion_sdk。

对现有直驱、Nav2、UWB 路径建立控制权表和停止证据。不直接增加速度 mux、不重路由所有 cmd_vel、不声称已有统一安全控制。这些变动若明显改变机器人行为，必须经人工确认和硬件验收。

## 5. Dependency Rules

### 5.1 源码/构建方向

~~~text
领域核心 -> 标准库/本模块必要依赖
模块 ROS/设备适配 -> 本模块核心 + 已注册公共接口/外部 SDK
集成 launch/tests -> 各模块公开入口与契约
模块实现 -X-> 另一个模块的内部实现
contracts -X-> 任何模块运行实现
vendor 算法 -X-> BT、Emotion、Voice 等业务模块
~~~

ROS 通信可以构成反馈环，Python/C++ 实现导入和构建依赖必须是 DAG。这两个图分别检查，不能以业务环为理由制造源码环。

### 5.2 可执行规则

1. 禁止通过 sys.path、PYTHONPATH 或仓库绝对路径导入兄弟模块内部代码。
2. 已有 generated srv/action 类型跨包导入列入显式 allowlist；它们不等于算法代码导入。
3. Python module tests 在只有本模块声明依赖的环境运行；禁止“主仓所有包都安装所以测试通过”。
4. 仅集成测试可同时协调多个实现，并按各自环境以独立进程运行。
5. 不创建笼统 common/utils。先确认语义相同、至少两个真实消费者，再考虑提取无业务逻辑的小库。
6. JSON schema/fixture 与 IDL 来源统一登记，但业务判定、阈值、行为目录和状态机不放入共享契约工具。
7. 消费者不直接读另一个模块私有 YAML、登记数据或日志。测试可检查公开行为目录之间的引用一致性。
8. Python 依赖、ROS package 依赖、原生链接依赖、部署制品依赖分别声明；不能互相替代。
9. 每个临时跨模块依赖记录 owner、原因、验收项和退出条件，不靠 TODO 无限保留。

### 5.3 当前优先解耦清单

| 当前依赖 | 近期处理 | 不做的动作 |
| --- | --- | --- |
| BT/Action 的接口类型自动回退 | 记录并测试有效类型，先观察，再做兼容的显式选择 | 不靠新增包改变自动选择 |
| Action 航点协议借用 VoiceTask | 登记为 navigation legacy contract，适配器封装其语义 | 不立即替换类型或伪造服务端 |
| BT/Action 行为/动作目录联动 | CI 校验标识引用和元数据传播 | 不把仲裁和执行业务合并 |
| Vision → Emotion 策略反馈 | 冻结输入与行为样例，保留适配边界 | 不擅自移除反馈 |
| RTAB → robot 内 OpenVINS | OpenVINS 作为固定 vendor 构建输入 | 不让 vendor 构建依赖机器人 bringup |
| Action subprocess 启动跟随 | 先保持并测试；后续 profile 可接管生命周期 | 不在同一 profile 同时启动两套跟随 |

## 6. Interface Strategy

### 6.1 冻结什么

每个接口登记：逻辑名字、完整 ROS 类型名、端点、方向、owner、已知消费者、QoS、frame/单位、时间来源、schema 版本、可选字段、超时/重试/去重、取消/终态、错误和能力缺失语义。

首批接口：

| 领域 | 要稳定的接口 | 初期 owner |
| --- | --- | --- |
| Vision | visual_event、object_detections、VisionTask、目标 epoch/id 和距离有效性 | Vision |
| Voice | audio_event、VoiceTask、interaction/utterance/wake ID、hold/release | Voice |
| Emotion/Needs | 两类 state/signal、人格/时间输入、行为结算输入 | Emotion |
| Behavior execution | ExecuteBehavior、attention_tracking、goal_lease | BT/Action 双方契约负责人 |
| Business result | /behavior/result_event 的映射范围与 metadata | BT 生产，Emotion 消费 |
| Person localization | LocateFromBbox、TF/深度时效与 navigation_required | Navigation |
| Navigation | NavigateToPose、Spin、现有 waypoint task/status | Navigation 能力 owner；缺失服务仍为 UNKNOWN |
| UWB | FollowUwb、RandomRoam、OrbitUwbOnce、SetBehavior | go2_uwb_behavior |
| Chassis | Go2 Request、Lite3 simple_cmd/status、Twist 出入口 | Action 适配负责人；外部实现 UNKNOWN |

Visual schema_version=1、Audio schema_version=2、Need/Emotion 各自版本属于不同协议，不强行改成同一个全局数字。

### 6.2 物理位置与 ROS 类型兼容

**当前已发布的 IDL 仍以现有包内文件为权威来源。** contracts/registry.yaml 引用它们并记录指纹；不复制第二份可编辑的 authoritative IDL。Schema、协议说明和跨模块 fixtures 可以集中放到 contracts/。

保留以下完整 ROS 类型身份：

- marsdog_vision_interaction/srv/VisionTask
- marsdog_voice_interaction/srv/VoiceTask
- marsdog_action_executor/action/ExecuteBehavior（当前本地可用来源）
- person_3d_localization/srv/LocateFromBbox
- go2_uwb_behavior 的现有 action/service

VisionTask 与 VoiceTask 字段相同也不等于相同 ROS 类型。Python alias 不能保证 wire compatibility。

**不在第一批迁移创建 marsdog_interfaces 并让现有自动优先导入生效。** 当前机器人若已经安装了仓库外的 marsdog_interfaces，必须先采集实际类型/IDL；不能断言生产必然使用本地 fallback。

目标是接口独立可消费，不是接口文件必须集中改名。现有类型所属包可以保留；先通过纯声明读取、轻量接口构建验证及独立消费者测试降低对运行实现的依赖。轻量构建模式如需添加，必须在原包身份下验证，不部署两个同名 ROS package 互相覆盖。

新跨领域协议在确有需求时可进入小型专用 interface package；如涉及旧协议迁移，采用新端点/类型版本、显式 bridge、旧客户端回归和退役窗口。任何不兼容切换必须人工确认，不作为本提案默认授权事项。

### 6.3 兼容级别

- C0：源码路径变化，wire、包名、解释器选择、默认参数、行为不变。
- C1：增加文档/测试/诊断或可选配置；旧配置仍等价，不自动启用新行为。
- C2：增加协议能力；必须验证旧消费者是否容忍新增字段/枚举，不能凭“只加字段”认定安全。
- C3：改类型、端点、必填字段、QoS、frame、单位、超时/取消语义或可见行为；暂停并确认。

### 6.4 运控、嵌入式边界

仅定义当前软件侧能力约束：发送现有速度/姿态/动作请求、观察已有状态、发起取消/停止、报告超时/不可用；适配器将其映射为已知 Go2/Lite3 接口。

未来协议必须明确控制权、frame/单位、时效、停止确认、能力和健康状态，但这些现在只作为需求清单，不编造消息字段、实时周期、关节结构或固件行为。

现有接口不能证明“机器人已停”时返回 UNKNOWN/未确认的测试证据，不能把发送零速或 cancel ACK 当作硬件停车证明。

## 7. Python Environment Strategy

### 7.1 决策：统一工具，保留独立项目和 lock

选择 uv 作为 Python 环境/锁文件管理的统一工具，保留各模块自己的 pyproject.toml、uv.lock 和虚拟环境。主仓根不建立包含所有模块的 uv workspace，也不建立全局 requirements 合集。

uv workspace 共享锁文件并整体求解；官方明确指出，依赖冲突或需要独立虚拟环境的模块不适合放进同一 workspace。因此这里采用独立项目，通过主仓薄命令统一调用，而不是使用 --package 假装隔离。[uv workspace 文档](https://docs.astral.sh/uv/concepts/projects/workspaces/)

只有出现真正稳定、低依赖的公共库时才使用显式 path/version dependency；当前不建立公共运行库来迫使环境互相依赖。

| 环境 | 初期策略 | 必须保留/检查 |
| --- | --- | --- |
| vision | 原锁和 Python 3.10，独立 venv | RKNN/模型 extras、cv2 提供方、原生库 |
| voice | 原锁和 Python 3.10，独立 venv | sherpa、RKLLM、音频/串口、setuptools pin |
| emotion | 独立项目；在包装等价验证后补齐锁/构建元数据 | 不增加原本不需要的 ML 依赖；保留 JSON 配置回退 |
| behavior | 原锁，独立 venv | rich/PyYAML、pytest 9、ROS 类型来源 |
| action | 原锁，独立 venv | NumPy 声明先保留，审计后单独处理；系统 Python 入口需真实验证 |
| contract/test tools | 独立开发工具环境 | 不进入机器人运行进程，不污染业务依赖 |
| ROS/native | OS/ROS 包与原生制品清单 | 不是 pip/uv lock 能完整锁定的环境 |

即使未来 Action 去掉无用途的 NumPy 声明，也不自动合并五个环境。工具统一、可重现部署和模块独立性已经达到目的。

### 7.2 版本、打包与解释器

- 当前 ROS 部署基线保持 Ubuntu 22.04 / Humble / 系统兼容 Python 3.10；本次不同时升级 ROS 或 Python。
- 可携带到别的 Python 版本的纯核心仅作为额外测试目标，不承诺全部原生推理支持。
- 项目迁入时保留当前 setuptools/hatchling/ament 构建后端，不在搬迁提交中统一改后端。
- 普通 Python 依赖以 pyproject 为来源；package.xml 表达 ROS/system 依赖；setup.py 保留 ament 必需入口并检查元数据一致性。
- 不把 rclpy、生成 ROS 类型和 cv_bridge 当作普通 PyPI 替代品。
- ROS 节点用与 Humble ABI 相容的解释器；每个 profile 记录可执行路径、sys.path、overlay 和 native library 来源。
- 需要系统 ROS Python 可见性时，由受控系统基础环境与独立 venv 组合；明确记录系统包可见范围，验证 NumPy/cv2 实际加载位置。不能仅靠 activate 猜测。
- 同一个模块实现不能同时从 editable install 和另一个 colcon overlay 的不同副本加载；启动 smoke test 验证 __file__ 和生成接口路径。
- 每个环境独占自己的目录；禁止多个模块 uv sync 指向同一个绝对环境目录。uv 文档说明这可能互相覆盖环境。[环境路径文档](https://docs.astral.sh/uv/concepts/projects/config/)

### 7.3 不在迁移中自动“修好”的依赖

NumPy 冲突、双 OpenCV 发行包、Torch CUDA 锁内容、pytest 主依赖、PySide2 缺失声明分别形成小变更和验收；禁止同时升级全部库。RK3588 的推理性能和稳定性必须由目标设备验证，x86 fake provider 不能代替。

整机发布以 release manifest 绑定主仓 commit、各模块 lock 哈希、OS/ROS 基础制品、vendor commit、模型哈希和有效配置；这才是整机可复现边界，不是一个 uv.lock。

## 8. ROS Workspace Strategy

### 8.1 源码位置与构建 workspace 分离

主仓按模块存源码，不再要求源码目录就是 colcon workspace 根。工具用明确的 base paths 和包清单生成构建计划，输出放到 out/<profile>/<layer>。初期允许各旧 workspace 原位构建作为对照。

构建依赖目标：

~~~text
L0  固定 OS / ROS Humble / 系统库与外部接口
  -> L1  vendor OpenVINS / VINS / UWB 等（按 profile 选择）
  -> L2  RTAB 核心及 ROS wrapper（OpenVINS profile 显式 WITH_OPENVINS=ON）
  -> L3  自研 sensors / navigation / 五个上层包（按 package DAG 排序）
  -> L4  整机 bringup、launch tests、集成发布
~~~

L3 中 srv/action 生产者先于消费者；package.xml 的现有遗漏按实际 import 单独补齐并验证。当前不存在的 marsdog_interfaces 不能以空包绕过构建；必须先确定所选 profile 的真实接口来源。

此结构消除“RTAB 构建必须 source 机器人 bringup”的概念环：RTAB 只依赖固定 OpenVINS 库；robot bringup 在上层引用 RTAB。

### 8.2 overlay 与 ABI 规则

- 使用明确基础前缀和固定层级，禁止隐式继承开发者历史 shell 的 AMENT_PREFIX_PATH/PYTHONPATH/LD_LIBRARY_PATH。
- 使用隔离安装和包来源检查，避免同名包从 apt、旧 workspace、新 workspace 同时可见。
- 替换 OpenVINS/RTAB ABI 时重建其所有相关下游，不只覆盖一个库。colcon 文档明确提醒覆盖非叶子包可能导致 API/ABI 和 Python 模块来源问题。[colcon overlay 文档](https://colcon.readthedocs.io/en/released/user/overriding-packages.html)
- 每个 profile 保存 colcon 包清单、依赖顺序、CMake options 和实际安装前缀。
- CI 既做开发 symlink 模式，也做非 symlink 的干净安装/启动检查，发现资源路径只在源码树下成立的问题。

### 8.3 Profile 与默认行为

初期规划三类 profile：simulation、lite3、go2；每类再显式选择 odometry、mapping/localization、following 和传感器来源。名称只是计划，不意味着已有经过验证的组合。

在采集生产基线之前不宣布某个 profile 为唯一默认；保留旧 launch。新 profile 先用于并行验证，通过后再切换入口。

Profile 必须说明：

1. 相机流、TF、时间来源、QoS、ROS_DOMAIN_ID/RMW。
2. 是否需要 color/aligned depth，不能只启动 infra 却宣称 Vision/人员定位就绪。
3. UWB 管线由 bringup 启动还是由 Action subprocess 启动；同一组合只能选一种。
4. 运动控制权、启用的速度路径、停机策略及当前 UNKNOWN。
5. 模型、厂商库、设备和外部服务缺失时的状态。
6. RTAB 数据库路径及是否有删除/重建选项，保留现有值但禁止工具无提示执行破坏性启动。

doctor 只检查前提，不启动运动、不修改设备频率、不建图覆盖数据库。新 release gate 可拒绝缺少真实执行器的生产验收，但不暗中改变旧节点的 Mock fallback 行为。

## 9. Third-party / RTAB-Map Strategy

### 9.1 选择固定 fork/快照，不把上游算法搬成自研

RTAB 初期以现有整个 rtabmap_ws commit 为获取单元；完整上游、local modifications、mono wrapper 一起保留。OpenVINS/VINS 从混合 robot 仓库的独立复制品提取，建立可追溯的固定 fork/快照。

主仓 third_party 清单记录来源 URL（未确定则明确未配置）、完整 commit、上游基线、许可证文件、维护角色、已知修改、构建选项和验收测试。没有确定远端时，可先使用本地已校验镜像，不编造 GitHub 组织或仓库地址。

不是默认采用 Git submodule：团队日常工作以一个主仓和显式依赖获取命令为入口；vendor 修改在受控 fork 完成，再通过“vendor commit + 主仓 lock 更新 + 集成报告”进入发布。

### 9.2 RTAB 已知修改与保留范围

现有 UPSTREAM_VERSIONS 记录核心 e321999b、ROS wrapper 2eef2b32。相对本仓库初始导入 a3473d1，后续八文件修改涉及外部速度测量、OpenVINS 腿速融合、ROS leg_odom、同步修复、地面分割和链接。

**这八文件不是相对上游的完整差异清单。** 初始导入是否包含其他修改仍需与上游对应对象比对。不能只导出这八个文件再拉取新上游，认为功能已完整保留。

rtabmap_openvins_mono 来源未充分确认，先留在 vendor 区域；它不是删除候选。

### 9.3 vendor 升级门禁

- 对比上游与本地基线，保留全部定制改动和许可证。
- RTAB + OpenVINS 成对测试：API/link、配置、IMU/leg velocity 时间戳与坐标系、退出稳定性。
- 使用相同回放输入比较轨迹、局部地图、定位重置和退出行为；容差由基线测量确定，不虚构阈值。
- 修改 vendor 版本必须重跑相关下游，而不是只编译该 vendor。
- 厂商 .so/.a 在取得来源/分发权限证据前不重新公开发布；这不妨碍在现有授权设备上保持旧部署。

## 10. Git History Migration Strategy

### 10.1 两条保留线

**原始历史完整保留；新主仓导入可追溯的模块历史。** 选择在副本上进行路径前缀变换和必要的子树筛选，再合入新主仓；不 squash 成一个“initial import”。

这会改变新主仓中导入 commit 的 SHA。不能同时宣称“改了所有历史路径”又宣称“原 commit SHA 全部不变”。原 SHA、refs 和对象保留在原仓及校验过的归档中；新历史通过 commit map 追溯。

### 10.2 步骤与验收

1. 为每个源建立 refs 清单、HEAD、可达对象/历史记录、文件模式和子模块/LFS 检查；原仓不改。
2. 从源生成完整镜像/bundle 并做 verify 和实际恢复演练；跨机器归档前核验缺失对象。Git bundle 用于 refs 可达历史，不代替工作区、LFS 或外部制品备份。[Git bundle 文档](https://git-scm.com/docs/git-bundle)
3. 为未提交/未跟踪/忽略数据单列清单。本次基线 clean 不等于没有重要 ignored 数据；模型、地图、录入等单独保管。
4. 仅在一次性导入副本使用固定版本的历史过滤工具；移动到目标前缀，并排除 vendor/build/data/敏感内容。路径过滤涉及历史改名时必须覆盖旧路径，不只匹配当前名称。
5. 保存 source ref → source commit → imported commit → target path 的映射、导入参数、工具版本和文件哈希清单；折叠/被过滤的提交映射状态明确记录。
6. 将模块历史合入新主仓，各 source 的 tags/branches 使用 source-id 命名空间，避免冲突。主仓首次发布记录原始及导入双方基线。
7. 用内容、可执行位、符号链接和样本 blame/log 验证；生产源码机械迁移提交不混入行为修改。
8. 原仓保持可恢复并继续可运行；各模块切换权威开发源时设明确冻结点，禁止长期双写。

历史过滤仅发生在副本，原 Git 历史不被重写。commit map 是该工具提供的可追溯产物之一。[git-filter-repo 文档](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt)

### 10.3 回滚与停止条件

回滚使用上一套完整 release manifest/旧部署前缀；不对有用户工作的仓库执行 reset。迁移时不改变运行数据格式，旧版本可继续读原数据。

归档不能恢复、源码哈希异常、历史路径缺失、敏感资料可能进入公开远端、重要数据无法确认归属时停止相关导入。历史签名保留在原始历史；变换后的提交不能伪称保留了原签名。

## 11. Testing Strategy

### 11.1 验证层次

| 层 | 验证内容 | 所需环境 | 通过条件 |
| --- | --- | --- | --- |
| T0 静态边界 | imports、package DAG、配置引用、IDL/schema 指纹、来源/许可清单 | 无机器人 | 无新增非法依赖、无未解释的契约差异 |
| T1 模块回归 | 原有纯 Python/C++ 单测、状态机、取消、目标锁定 | 每模块独立环境 | 基线与迁移结果等价；新增失败为阻断 |
| T2 包装/安装 | wheel/ament/CMake、配置和资源加载、入口、非源码 cwd 导入 | 干净支持平台 | 无源码绝对路径依赖；解释器/包来源正确 |
| T3 ROS 契约 | 真正生成的 IDL、跨进程 Pub/Sub/Service/Action、QoS/metadata/cancel | Humble | 旧客户端与迁移服务端及反向组合通过 |
| T4 集成回放 | 感知→需求/BT→Action fake→结果结算；导航/跟随 fake | 无运动硬件 | 同输入的可观察状态/行为序列等价 |
| T5 硬件验收 | NPU/音频/设备、SLAM/导航、停止和真实行为 | 已登记目标机器人 | 实测满足已批准基线，缺设备不能标成功 |

fake 是测试替身，不是实现了缺失的生产服务。测试报告必须标注真实、模拟、跳过、阻断，跳过不能冒充通过。

### 11.2 复用现有测试

- Emotion：need/emotion split、需求生命周期、energy、配置、时间、perception adapter、ONE1000。
- BT：runtime architecture、preemption、cooldown、voice engagement、attention lifecycle、recharge lifecycle。
- Action：goal deadline、cancel/arbitration、metadata、person approach、waypoint、UWB、Go2/Lite3。
- Vision：visual contract、目标定位、stranger policy、模型/backend、Fast DDS、入口和配置。
- Voice：voice contract、session recovery、NLU、audio capture、登记和配置。

这些测试已存在，不以新测试框架替换它们。先建立基线，再填跨模块缺口。

### 11.3 必须覆盖的跨模块场景

1. visual/audio 正常事件、缺失可选字段、重复事件、未知事件和陈旧事件。
2. 同一目标重启换 epoch，不得错误复用旧 target_id。
3. 语音会话 hold/release 与 BT goal 生命周期一致。
4. 旧行为请求取消但尚无终态时，新行为的交接保持原语义。
5. Action result metadata 经 BT 映射到 Needs；包括充电值规范化、重复结算、中断规则。
6. 需求触发/回落、情绪反馈、人格/时间与随机种子固定下的基线。
7. 导航/航点/UWB 不可用、超时、cancel accepted 但 stop unconfirmed。
8. 缺执行器时的现有 Mock 路径可观察；生产验收必须识别其不是实机能力。
9. 安装目录中的模型/配置路径与旧入口可运行性；模型缺失显式记录。
10. 同一 profile 的传感器话题/TF、速度生产者、跟随启动责任不冲突。

不建立全局 RobotState 测试模型来重写系统。回放比较模块真实可观察输出；只归一化时间戳、临时 ID 等明确非语义字段。

### 11.4 第一批验证执行限制

本轮提案不运行测试。后续第一切片先检查测试副作用；在临时输出目录禁用 bytecode/cache 或指定缓存，禁止连接生产 ROS domain/串口、播放音频、触发运动。

缺少 ROS 或模型时，将对应项标为 BLOCKED/NOT RUN 并继续不依赖它的验证；不能依据 pytest 的纯 mock 结果宣布整机迁移完成。

## 12. CI Strategy

### 12.1 CI 结构

选择 GitHub Actions 作为计划中的默认 CI 编排，job 脚本保持本地可运行；远端和凭据尚未配置。初期不引入 Bazel、Nix、Kubernetes 或自建调度平台。

PR 检查：

- T0 契约与边界检查：所有 PR。
- 受影响模块 T1/T2：模块独立矩阵；同时包含其契约消费者。
- 契约/launch/ROS build/vendor manifest 修改：触发相关 ROS T3/T4。
- 完整软件回归与原生构建：定期及发布候选。
- ARM64/RK3588、真实音频、机器人运动：受控硬件任务，不由任意外部 PR 自动执行。

变化影响图由 modules.yaml 和 contracts registry 生成，不只根据“改了哪个目录”决定。共享构建/profile/schema 变化需扩大测试范围；vendor ABI 变化重建所有实际下游。

### 12.2 可重现与质量门

- 固定 uv/构建工具版本；使用已提交 lock，CI 不自动升级或改写锁文件。
- OS/ROS 基础镜像或软件包快照固定到可追溯版本；记录原生 ABI 和安装来源。
- 缓存键包含架构、Python、ROS 基础、lock、vendor commits、编译选项；不能跨 ARM/x86 或 ABI 复用。
- 初期格式/lint 只约束新文件与触碰范围，不做第三方格式化或全仓噪声提交。
- 既有失败建立基线记录和 owner；不能用永久 ignore 隐藏新增失败，也不能删除断言让迁移过关。
- 每个发布候选必须有模块、ROS、配置、接口、来源和测试报告；硬件项未通过则只标软件候选。

### 12.3 Ownership / CODEOWNERS

| 路径/职责 | 角色 owner | 额外审查 |
| --- | --- | --- |
| modules/vision | Vision maintainer | 契约变更由消费者复核 |
| modules/voice | Voice maintainer | 同上 |
| modules/emotion | Needs/Emotion maintainer | 结算语义需要 Behavior owner |
| modules/behavior | Behavior maintainer | 执行生命周期需要 Action owner |
| modules/action | Action maintainer | 底盘/停止相关需要硬件负责人 |
| modules/navigation、sensors | Robotics maintainer | vendor/API 改动需对应 vendor owner |
| contracts、integration、platform | Platform maintainer | 生产者及受影响消费者至少各一方 |
| third_party | Robotics/vendor maintainer | 来源、许可、ABI 验收 |

本表是角色模型，不虚构 GitHub 用户/团队。正式 CODEOWNERS 生成前绑定真实账号。不存在的 @team 不应提交成看似有效的审查规则。

### 12.4 AI Agent 开发约束

根 AGENTS.md 提供架构入口、每模块测试命令、路径/依赖规则、ROS 类型保护和禁止碰硬件事项；模块文档说明公开 API、内部实现与资源前提。

跨模块功能的默认完成标准：同一个 PR 内列出契约生产者/消费者、更新样例、运行影响闭包测试、记录 profile 影响。不能只改生产者再让人记得去改其他仓库。

## 13. Migration Phases

每阶段的 build/import/test/ROS dependency/config/interface 六类检查必须有结果；不适用项写明理由，缺环境项标阻断。阶段门通过才进入依赖它的下一阶段，不以日期强行推进。

| 阶段 | 范围/交付 | 验收门 | 回退 |
| --- | --- | --- | --- |
| P0 本轮方案 | 本文、决策、风险、自审 | 事实与 UNKNOWN 分离，范围清楚 | 只修改文档 |
| P1 基线与契约切片 | 源清单、接口指纹、已有测试基线、跨模块结果回归、类型来源观察 | 旧源码/配置/历史不变；复现基线；报告真实/模拟/未运行 | 删除新增工具/报告即可，不触碰业务 |
| P2 首个实现迁移 | 新主仓最小骨架、保全历史；Emotion 模块迁入 | 源码等价、单测/安装/ROS 状态与结算等价 | 继续使用原 Emotion repo/安装前缀 |
| P3 决策与执行 | BT 后 Action 分步迁入，联调；保留协议/默认参数 | 取消、抢占、会话、attention、结果链与旧端互通 | 切回成套旧 BT/Action profile |
| P4 感知模块 | Vision、Voice 分别迁入；独立锁和制品路径 | fake 与真模型分开验收；事件/服务/录入/会话兼容 | 保留旧环境、模型和数据目录 |
| P5 Robotics/vendor | robot 自研包分类迁入；固定 OpenVINS/RTAB/VINS/UWB；明确 build DAG | 构建及安装闭合、轨迹/地图回放、TF和局部控制验证 | 原 vendor commits + 原 workspace |
| P6 整机切换 | 新 bringup/profile、release manifest、CI 与所有权落地 | 软件全回归 + 选定生产组合硬件验收 | 上一完整发布清单 |
| P7 有证据的清理 | 重复工具、旧入口、依赖冗余逐项处理 | 消费者清单、使用证据、兼容窗口满足 | 各小提交单独撤回 |

P5 的 vendor provenance/历史归档调查可在早期并行于其他非依赖工作，但不提前替换生产算法。

P7 删除/停用用途不明的代码前必须询问；“legacy”“mock”“deprecated”注释不构成生产废弃证明。

### 13.1 每次迁移的最小审查包

- 源/目标 commit 和模块路径映射。
- 机械移动 diff 与后续修复 diff 分离。
- 默认配置/入口/ROS 类型/QoS/资源路径的对照。
- 六类验证结果及明确失败/未运行列表。
- 回滚命令或入口说明，但不在报告生成时执行。
- owner 与受影响模块确认记录；仅涉及用户列出的重大边界时向用户暂停询问。

## 14. Risks

### 14.1 最大五项风险

| 优先级 | 风险 | 检测/限制 | 不能用来掩盖问题的做法 |
| --- | --- | --- | --- |
| 1 | 实际部署接口与本地基线不同；自动导入切换导致互不通信 | P1 采集完整类型来源、旧新组合测试 | 先建 marsdog_interfaces 再说 |
| 2 | 运动多路径、停止/取消语义和电量真值不完整 | 保留行为；能力/控制权表；硬件项单列、必要时人工确认 | 新增全局 mux、虚构 BMS、cancel ACK 当停车 |
| 3 | 环境/ABI/制品不可复现 | 独立 locks + ROS/native/vendor/model release manifest | 单环境强行降/升依赖，x86 mock 代替 NPU |
| 4 | RTAB/OpenVINS 定制被丢失或顺序错误 | 整个当前 vendor snapshot 固定，完整上游差异审计，联动重建/回放 | 只保留八个后续修改文件，直接拉最新上游 |
| 5 | 历史/运行数据丢失或新旧源长期双写 | 原始归档恢复演练、commit map、数据分离、模块切换冻结点 | 在原仓 filter/reset、复制当前文件当历史保留 |

### 14.2 其他风险

- 未知生产 launch 被误判废弃：保留，确认后才退役。
- waypoint server 不在当前范围：测试替身可用于契约测试，发布报告明确真实能力缺口。
- 拆包过多提高日常成本：首次迁移保持五个模块 package 粒度，核心/ROS 先逻辑分层再评估物理拆包。
- “公共契约”变成业务中心：只存协议和测试资产，禁止阈值、仲裁、模型、设备控制进入。
- 目标目录移动破坏 package-data/脚本相对路径：干净安装、非源码 cwd、旧 launch smoke 必须覆盖。
- 新 CI 只检查生产者：影响闭包从契约登记生成，新增消费者必须登记。
- 真实资料/厂商库分发权限不明：不删除原件、不重新公开分发，记录来源和待确认项。

## 15. First Migration Slice

### 15.1 选择与范围

**第一切片：基线清单 + 现有接口兼容测试 + Action→BT→Needs 的结果回归链。**

这是可验证的小切片，不搬运行实现、不新建运行接口包、不改变机器人行为。它先解决“未来移动后如何知道没坏”的问题。

选择结果链的原因：三个模块已有对应测试和窄接口；无需相机/NPU/真实运动即可验证 metadata、状态转换和结算语义。充电 metadata 仅作为已存在协议样例，不证明真实电池读数。

### 15.2 计划新增产物

在后续实施阶段，先建立独立的迁移验证目录/分支，新增以下内容；原仓只读引用：

~~~text
migration/
  baseline/sources.json
  baseline/interfaces.json
  baseline/known-gaps.md
  baseline/ownership.md
  fixtures/behavior-result/
  tools/check_baseline.py
  tools/run_module_checks.py
  tests/test_result_pipeline.py
  reports/<run-id>/
~~~

这些将来归入主仓 contracts/tests/tools/docs，不作为永久“第八个业务模块”。

### 15.3 实施顺序

1. 记录七库 HEAD、状态、IDL、相关配置指纹和导入环境前提；扫描 AGENTS/ownership 和重要 ignored 数据但不读取私人录入内容。
2. 建立独立运行器，分别执行 Action、BT、Emotion 的现有相关测试；每个模块独占环境和进程。
3. 固定合成输入，Action 的现有结果创建路径输出 metadata；通过测试文件/stdio 交给 BT 的现有 mapper；再交给 Needs 现有 adapter。
4. 跨进程文件/stdio 仅是测试编排方式，不新增生产 IPC；禁止在一个测试进程中用 sys.path 塞进三个仓库来掩盖依赖冲突。
5. 检查成功、失败、超时、中断、重复 event、energyValue 别名/边界、非需求行为不结算。断言基于当前源码/已有测试，发现差异先定位，不修改产品语义。
6. 加入 IDL/端点/类型来源指纹检查和原有 cancel lifecycle 测试，作为后续机械迁移的门禁。
7. ROS 环境可用时，在独立测试 domain 用真实生成 ExecuteBehavior 类型和 fake server 跑反馈/终态 smoke；不可用则清楚标 BLOCKED，不伪造通过。
8. 对现有包执行可用的构建/安装/import/config 检查；本切片不修复全部历史问题，形成带证据的缺口列表。

### 15.4 验收标准

- 七个原仓库 tracked/untracked 状态、HEAD、协议和默认配置没有改变。
- 基线清单可再次运行并检出人为制造的接口/配置偏差（在测试副本中验证）。
- 三模块在各自环境通过相关现有测试；跨进程结果链与当前单模块结算规则一致。
- 实际 ROS smoke 与非 ROS 回放分别报告，取消生命周期不能只有 source-string 断言。
- 源码路径不是安装导入成功的必要条件；包装不足明确列为后续修复项。
- 每个检查有命令、环境、结果、输出位置；缺依赖不自动安装到系统，也不跳过后宣布完成。
- 没有发布实机运动命令、连接生产设备或创建生产模型/状态数据。

### 15.5 随后的第一个实现迁移

选择 Emotion/Needs：核心已有明确类和大量需求/时间/事件测试，没有模型和复杂原生推理依赖。

迁移时保留 marsdog_core、marsdog_ros2、marsdog_need_emotion、launch 名称及 configs；先整模块移动，再单独解决打包元数据和可选 ROS import 边界。不得把“迁移 Emotion”顺带变成重写需求算法、统一世界状态或重新定义中断结算。

如果 P1 证明某个未知包装/运行约束让 Emotion 的风险高于预期，先修复该小约束并复核，必要时调整次序；不能因为既定计划继续错误迁移。

## 16. Architecture Review and Revisions

已进行一次针对本提案的架构自审。以下是被否决或修订的初始倾向及最终结论：

| 审查问题 | 初始风险 | 修订后决策 |
| --- | --- | --- |
| 有没有过度设计？ | 先拆成大量 core/adapter/plugin 包、建公共 SDK | 首次保留模块现有 package 粒度；仅有真实复用和测试收益才继续拆 |
| 有没有新的单点模块？ | 统一 RobotState/平台 broker/全局 coordinator | 不新增运行中心；bringup 只组合；contracts 仅资产和规则 |
| 有没有循环依赖？ | 把 Emotion 塞进 BT、RTAB 构建依赖机器人 overlay | 领域状态独立；源码 DAG 与通信反馈分开；vendor OpenVINS 下沉 |
| 有没有把业务逻辑放 common？ | 为去重搬入阈值、行为目录、目标选择 | 不建 generic common；共享协议不包含决策 |
| 有没有把第三方当自研？ | 整个 robot_ws/rtabmap_ws 原样铺进 modules | 自研分类迁入；算法/vendor 固定 fork；来源不明留 vendor |
| 有没有牺牲独立性？ | 一个 uv workspace 和 root test 环境 | 每模块项目/lock/环境，独立安装测试，跨模块用进程协调 |
| 是否仍靠大量人工协调？ | 契约目录只是文档、测试按目录选 | 契约 producer/consumer 登记驱动影响闭包；同 PR 提交双方变化和回归 |
| 是否增加多份配置真值？ | modules/contracts/build/release 手工重复同一依赖图 | 各清单职责分开，引用原始包声明；依赖图和发布清单生成并校验 |
| 是否会偷偷改变 ROS 协议？ | 创建 marsdog_interfaces 满足声明 | 保留原类型；先识别优先导入风险；新类型不默认替换旧端点 |
| 是否遗漏真实行为？ | 将所有中断一概视为不结算 | 已有 Emotion 测试证明部分中断会影响需求；纳入兼容回放 |
| 是否假装保留所有 SHA？ | 历史前缀变换后宣称 SHA 未变 | 原对象归档 + 导入 commit map，明确变换历史 SHA 会变 |
| 是否把八文件当全部 RTAB 定制？ | 仅导出初始导入后的 diff | 固定完整 snapshot，另核对初始导入对上游的差异 |
| 是否“修风险”反而改机器人？ | 加 mux、禁止所有 fallback、替换 BMS 值 | 先诊断/测试/发布门，不改现有节点语义；行为变更另行确认 |

审查结论：方案保留必要的集成治理，但不要求一次性完成目录、包、协议和算法四层重构。最大的未决项在真实部署和硬件语义，不能靠文档设计消除。

## 17. Key Architecture Decisions

| ADR | 决策 | 主要收益 | 代价 |
| --- | --- | --- | --- |
| ADR-001 | 自研主仓 + 固定 vendor/制品，保留独立模块 | 跨模块功能可一个 PR 验证，算法来源清楚 | 需要依赖获取和发布清单 |
| ADR-002 | 稳定现有 wire identity；契约先行，不立即集中改名 IDL | 减少旧客户端和混合部署断链风险 | 暂时保留生成接口的跨包依赖 |
| ADR-003 | 统一 uv 工具与检查，模块独立 lock/venv | 避免已知冲突，独立可测 | 多个 lock 需自动化维护 |
| ADR-004 | BT 决策、Action 执行、Emotion/Needs 权威状态、Navigation 提供能力 | 跨模块责任可解释，不复制业务引擎 | 要持续检查原有边界例外 |
| ADR-005 | 先基线/契约测试，后小步迁移；原始历史保全并映射 | 可验证回退，不重写成熟算法 | 前置验证需要投入，迁移不能一把完成 |

这些决定已在本提案中作出；普通目录/工具/包内分层不再逐项请求用户裁决。

## 18. Human Confirmation Boundaries

**当前文档与第一验证切片不需要人决定目录命名或锁文件方案。** 以下是触发对应阶段时才需要确认的事项，不阻塞无关工作：

| 事项 | 需要人提供/决定的内容 | 未确认前可继续什么 |
| --- | --- | --- |
| 生产基线 | 哪些机器人/launch/配置是实际生产；是否存在仓库外 marsdog_interfaces 和 waypoint server | 静态登记、纯回归、软件 fake 集成 |
| 代码退役 | 无法证明用途的 legacy/mock/旧驱动是否仍生产使用 | 保留原入口和源码，继续迁移已确认模块 |
| 产品/运动语义 | 多路径控制权、STOP/解除 STOP、真实电量/充电成功条件，以及任何会改变可见行为的策略 | 记录 UNKNOWN、观察和兼容测试，不改语义 |
| 外部协议 | 任何新运控/嵌入式字段、消息或时效要求的协议批准 | 现有软件端口与适配器测试，不编造底层实现 |
| 不兼容接口 | ROS 类型/端点/必填字段/QoS/取消语义的破坏性切换及退役窗口 | 维持原类型，继续纯路径与包装迁移 |
| 历史/数据 | 删除原始历史、不可恢复运行数据，或处理敏感/不明归属内容 | 副本导入与可恢复归档；不删除原件 |
| 发布所需信息 | 真实代码 owner 账号、远端位置、模型/vendor 制品来源与可分发范围 | 使用角色 owner 和本地固定来源，不虚构账号或公开分发 |

硬件运行和现场运动验收在部署窗口及现场责任人确定后执行。方案没有要求现在为未来所有阶段一次性批准。

## Appendix A. Evidence Index

以下链接指向本次分析目录中的真实文件；长期来源由第 1 节 source ID、commit 和仓库相对路径共同定位，迁移后不能只依赖当前机器绝对路径。

| ID | 证据 | 支撑结论 |
| --- | --- | --- |
| B01 | [Vision node](/home/elephant/MarsDog/MarsDog/marsdog_vision_interaction/nodes/vision_interaction_node.py)；[visual contract](/home/elephant/MarsDog/MarsDog/marsdog_vision_interaction/messages/visual_event.py) | 视觉发布/服务/情绪输入与目标协议 |
| B02 | [Voice node](/home/elephant/MarsDog/MarsDogVoiceInteraction/marsdog_voice_interaction/nodes/voice_interaction_node.py)；[audio contract](/home/elephant/MarsDog/MarsDogVoiceInteraction/marsdog_voice_interaction/messages/audio_event.py) | 语音事件、会话能力 |
| B03 | [Need system](/home/elephant/MarsDog/MarsDogEmotion/marsdog_core/need_system.py)；[Emotion system](/home/elephant/MarsDog/MarsDogEmotion/marsdog_core/emotion_system.py) | 独立领域计算 |
| B04 | [Need/Emotion tests](/home/elephant/MarsDog/MarsDogEmotion/tests/test_need_emotion_split_systems.py)；[config loader](/home/elephant/MarsDog/MarsDogEmotion/marsdog_core/config_loader.py) | 中断结算、边界、源码/share 配置回退 |
| B05 | [BT runtime](/home/elephant/MarsDog/20260702_MarsDogTree/marsdog_behavior/runtime.py)；[ROS node](/home/elephant/MarsDog/20260702_MarsDogTree/marsdog_behavior/ros_node.py:374) | 仲裁与接口回退 |
| B06 | [BT result mapper](/home/elephant/MarsDog/20260702_MarsDogTree/marsdog_behavior/result_event_mapper.py)；[recharge lifecycle tests](/home/elephant/MarsDog/20260702_MarsDogTree/tests/test_recharge_result_lifecycle.py) | 结果业务映射与 metadata |
| B07 | [Action stage executor](/home/elephant/MarsDog/20260707_MarsDogAction/marsdog_action_executor/stage_executor.py)；[ROS node](/home/elephant/MarsDog/20260707_MarsDogAction/marsdog_action_executor/ros_node.py) | 高层技能执行、底盘/导航与配置电量 |
| B08 | [Action ros2_compat](/home/elephant/MarsDog/20260707_MarsDogAction/marsdog_action_executor/ros2_compat.py)；[ExecuteBehavior IDL](/home/elephant/MarsDog/20260707_MarsDogAction/action/ExecuteBehavior.action) | 新增接口包会影响自动类型选择 |
| B09 | [waypoint adapter](/home/elephant/MarsDog/20260707_MarsDogAction/marsdog_action_executor/adapters/waypoint_nav_adapter.py)；[UWB config](/home/elephant/MarsDog/20260707_MarsDogAction/config/uwb_follow.yaml) | VoiceTask 借用、停止终态、路径依赖 |
| B10 | [Vision pyproject](/home/elephant/MarsDog/MarsDog/pyproject.toml)；[Voice pyproject](/home/elephant/MarsDog/MarsDogVoiceInteraction/pyproject.toml) | Python 3.10、NumPy<2、硬件推理依赖 |
| B11 | [Action pyproject](/home/elephant/MarsDog/20260707_MarsDogAction/pyproject.toml)；[BT pyproject](/home/elephant/MarsDog/20260702_MarsDogTree/pyproject.toml) | NumPy/pytest 冲突与打包差异 |
| B12 | [robot build](/home/elephant/MarsDog/slam/robot_ws/scripts/build_all.sh)；[source_all](/home/elephant/MarsDog/slam/robot_ws/scripts/source_all.sh)；[environment](/home/elephant/MarsDog/slam/robot_ws/scripts/setup_robot_env.sh) | 构建遗漏、RTAB 路径、加载副作用 |
| B13 | [RTAB provenance](/home/elephant/MarsDog/slam/rtabmap_ws/UPSTREAM_VERSIONS.md)；[RTAB CMake](/home/elephant/MarsDog/slam/rtabmap_ws/src/rtabmap/CMakeLists.txt) | vendor 版本与 WITH_OPENVINS 默认 OFF |
| B14 | [OdometryOpenVINS](/home/elephant/MarsDog/slam/rtabmap_ws/src/rtabmap/corelib/src/odometry/OdometryOpenVINS.cpp)；[mono package](/home/elephant/MarsDog/slam/rtabmap_ws/src/rtabmap_ros/rtabmap_openvins_mono/package.xml) | 定制融合与来源不明 wrapper |
| B15 | [UWB upstream API](/home/elephant/MarsDog/slam/robot_ws/go2_follow_ws/src/go2_uwb_behavior/docs/UPSTREAM_API.md)；[behavior launch](/home/elephant/MarsDog/slam/robot_ws/go2_follow_ws/src/go2_uwb_behavior/launch/behavior_follow_roam.launch.py) | 局部行为能力、互斥与停止语义 |
| B16 | [BT runtime tests](/home/elephant/MarsDog/20260702_MarsDogTree/marsdog_behavior/tests/test_runtime_architecture.py)；[Action metadata tests](/home/elephant/MarsDog/20260707_MarsDogAction/tests/test_recharge_result_contract.py) | 第一切片可复用的测试与生命周期 |

## Appendix B. Proposal Verification Record

- 已重新核对七个 HEAD 和工作树状态，见第 1 节。
- 已复读决定环境、类型回退、状态结算、构建层级和第一切片的关键源码/现有测试。
- 已核对 uv workspace/environment、colcon overlay、Git bundle/history filtering 的官方文档；技术引用见相关章节。
- 已校验全部 15 个要求章节、33 个本地源码证据链接和 Markdown 代码块配对；本轮最终复核时七个原仓库均为 clean。
- 架构自审和修订记录见第 16 节；未将其冒充第二位独立评审人的意见。
- 本轮未运行项目 build/test，未安装工具或依赖，未生成接口，未创建新 Git 仓库或改变原历史。
- 下一步是 P1，不是立刻合并七库或改变生产部署。
