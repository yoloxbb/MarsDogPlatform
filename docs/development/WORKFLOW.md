# 模块边界与功能开发

当前架构、环境与已知缺口见 [系统基线](../architecture/SYSTEM_BASELINE.md)。五人团队按照
[责任表](../OWNERSHIP.md) 和 [工程规范](ENGINEERING_STANDARD.md) 开发；跨模块功能先填写
[功能规格](templates/FEATURE_SPEC.md)，由功能负责人汇总链路验收。

## 已落地的依赖方向

Vision/Voice 通过原有 ROS 事件与任务服务对接上层。BehaviorTree 决定做什么以及何时
抢占，Action 负责如何分阶段执行并返回终态，Emotion/Needs 负责需求状态和结算。
Action 通过现有适配边界请求导航/外部能力；它不是缺失的底层运控算法。
不得通过 import 进入另一模块内部替代通信边界。

业务行为按 [两类行为来源](../architecture/BEHAVIOR_DRIVES.md) 区分触发路径，不按感知模块分类。
视觉、听觉、触觉中的部分事件直接生成候选，部分只影响情绪；具体事件是否同时走两条路径，
须在功能规格中列明对应规则。情绪达到触发条件后生成内部候选，生理和心理需求也归内部触发。
两类共用候选池、仲裁与 Action 执行。来源决定状态归属，优先级和动作模板单独定义；
复用情绪表达模板的直驱行为不自动取得内部情绪的生命周期。触觉影响情绪的消费入口已存在，
touch_direct 已有摸头、摸耳、碰鼻的软件预设与独立契约，实物采集仍待传感器。

~~~mermaid
flowchart LR
  Vision -->|感知事件| BT[BehaviorTree]
  Voice -->|语音事件| BT
  BT -->|现有任务服务| Vision
  BT -->|现有任务服务| Voice
  Vision -->|命中具体事件的内部状态规则| Needs[Emotion / Needs]
  Voice -->|命中具体事件的内部状态规则| Needs
  Touch[触觉] -->|已有情绪事件规则| Needs
  Touch -->|命中触觉直驱预设| BT
  Needs -->|内部状态及触发信号| BT
  BT -->|结果与证据| Needs
  BT -->|目标 / 取消| Action
  Action -->|反馈 / 终态| BT
  Action -->|现有航点接口| Nav[waypoint / Navigation]
~~~

这张图表示领域职责；具体消息身份、方向和兼容例外以 interfaces 登记及
[已落地架构自审](../architecture/PLATFORM_IMPLEMENTATION_REVIEW.md) 为准。
工具只装配进程、环境和测试，不新增运行时业务总线或所有模块共同依赖的业务 common。

当前运行链路、激活与抢占条件见 [事件到行为到动作详图](../architecture/EVENT_BEHAVIOR_ACTION.md)；
逐项配置映射见 [事件行为动作索引](../architecture/EVENT_BEHAVIOR_ACTION_INDEX.md)。

命名约定与已知映射缺口见 [标识规范及目录](../../interfaces/naming/README.md)。
修改登记的配置后先运行 `check_identifiers.py --refresh --python modules/action/.venv/bin/python`，
再运行 `dev.py check` 和受影响的契约测试；新缺口不会自动豁免。

新增功能可从 [能力清单与功能草稿](FEATURE_WORKFLOW.md) 开始；
实现后用 [录音试用](RECORDING_TRIAL.md) 观察真实 ASR、候选仲裁与动作终态。

共享日志只提供标准库基础设施，不承担业务通信；使用与扩展见 [统一日志](UNIFIED_LOGGING.md)。

## 开发示例：已有“回家”功能的扩展

先确定是 Voice 识别/入口变化、BT 仲裁变化、Action 执行阶段变化，
还是 waypoint 导航变化。一个需求可以在同一 PR 内修改这些目录及集成用例，
不再需要在七个仓分别提交/协调版本。

顺序是：写清输入事件与既有 action_id 的关系、取消/失败的预期；
在 owning module 增加测试；修改它的实现；补消费侧契约与隔离集成。
如果需求改变“回家是否结算 Energy”这类产品语义，需要先明确决策，
不能为了让测试通过自行增加结算或模拟电量。

新技能不通过 BT 直接执行导航/模型内部函数。先检查现有 Action 能力与接口是否能表达，
保留原动作证据门限；缺外部设备协议时记录 UNKNOWN，不虚构成功执行。

## 按变更选择门禁

| 变更 | 本地必选 | 额外验证 |
| --- | --- | --- |
| 任意源码/工具 | dev.py check | 受影响模块 dev.py test |
| Python 打包/资源/入口 | 模块单测 | check_<module>_install.py |
| Voice→BT/Emotion 声音事件 | 三模块单测 | check_audio_contracts.py；固定 v2 样例与容错差异 |
| Vision→BT/Emotion/Action 视觉事件 | 受影响模块单测 | check_visual_contracts.py；固定 v1 样例与缓存/边沿 |
| Emotion/Needs→BT 状态/信号 | 两模块单测 | check_state_contracts.py；权威/恢复/阈值 |
| VoiceTask/VisionTask envelope 或任务分发 | 各自全量单测 | Humble 下 check_task_contracts.py；保持 ROS 类型身份 |
| 执行/会话/取消协调组件 | 模块单测 + 对应契约 | 五模块安装检查含组件导入/源码哈希；Action 另跑 check_action_callbacks.py、check_action_transport.py、check_action_shutdown.py |
| Action→BT→Needs 结果/证据 | 三模块单测 | check_contracts.py |
| ROS IDL / service / action | 架构和原 IDL 兼容检查 | 生产方/消费方测试、build、doctor、对应 DDS 测试 |
| 感知会话/缓存/进程恢复 | 受影响模块单测 + 对应契约 | check_business_scenarios.py；七项安装后 DDS 恢复场景 |
| 进程组合/运行配置 | 平台测试 | 默认 smoke + check_local_lifecycle.py |
| waypoint/Nav2 | 原导航契约 | 可选真实 Nav2 smoke、check_nav2_recovery.py |
| C++/CMake/ROS package | package 依赖 DAG | check_robotics.py 或对应扩展 ROS build/runtime |
| 锁或第三方快照 | 所属独立环境 / 哈希 | 干净安装/编译与许可来源审查 |

当前 CI 按模块分 job，基础架构检查复用 dev.py check。
Humble 集成仅在手动触发的专用 localhost runner 上运行，默认不使用硬件。
GitHub 远端为 yoloxbb/MarsDogPlatform；专用 Humble runner 尚未配置。
远端工作流状态以 Actions 记录为准，本地证据在 validation。
不引入复杂增量 CI 推断：先保证所有模块 job 可独立复现，再按实际耗时优化。

## 历史与第三方

旧仓到新路径和 Git 提交映射在 docs/migration、integration/migration/baseline。
所有新代码以本仓为权威。third_party 管理来源/固定提交，.external 是可重建输出；
RTAB 的本地定制 fork 保留，不能用随手下载的 upstream 覆盖。
模型/构建输出/虚拟环境/设备私有配置不跟随功能 PR 提交。

五模块已完成的职责划分与全部门禁见 [兼容性重构](../architecture/COMPATIBILITY_REFACTOR.md)。

后续组件解耦和交付任务见 [渐进重构路线](../architecture/REFACTOR_ROADMAP.md)。
首个代表切片为 [叫过来与唤醒靠近](scenarios/CALLER_APPROACH.md)：当前明确区分视觉目标查询、
三维定位和导航执行。第四批已接入显式三模式靠近及几何调用，实机配准、TF 与停车仍需设备证据。
跨领域协议入口见 [应用协议目录](../../interfaces/application/README.md)。
第四批新增 [显式三模式靠近](../../interfaces/application/approach/README.md) 与
[触觉直驱／情绪双消费](../../interfaces/application/tactile/README.md)。相关变更增加
`python3 tools/check_approach_tactile_contracts.py`；安装后靠近 DDS probe 仅在 localhost domain 216 运行。

业务场景与各门禁的覆盖关系见 [验收矩阵](BUSINESS_SCENARIOS.md)。
导航/避障修改前先核对 [负责人交接](NAVIGATION_HANDOFF.md)，保留现有终态与恢复锁约束。

第五批事件分流和能力快照沿用 `check_identifiers.py`、`capabilities.py`，使用方法见
[事件清单与发布记录](../../interfaces/naming/EVENT_ROUTING.md)。纯清单/工具改动运行 `dev.py check`、
`check_identifiers.py --live --python modules/action/.venv/bin/python` 和能力生成；
报告引用不自动构成单项能力验收，原配置与冻结基线继续由原 owner 维护。

第六批新增 33 个表达预设及 Stage 取消入口保护。剩余 16 个能力已登记具体接入依赖；
详见 [社交表达预设与缺口处置](SOCIAL_EXPRESSION_PRESETS.md)。软件计划存在不代表底盘可用或真机验收通过。

收尾版本新增 [显式协调端口和应用所有权](REFACTOR_CLOSEOUT.md)；Voice/Action 协调变更继续跑全量单测及安装，NavigationTask 变更跑新旧两种类型的航点 DDS 测试。
