# 模块边界与功能开发

## 已落地的依赖方向

Vision/Voice 通过原有 ROS 事件与任务服务对接上层。BehaviorTree 决定做什么以及何时
抢占，Action 负责如何分阶段执行并返回终态，Emotion/Needs 负责需求状态和结算。
Action 通过现有适配边界请求导航/外部能力；它不是缺失的底层运控算法。
不得通过 import 进入另一模块内部替代通信边界。

~~~mermaid
flowchart LR
  Vision -->|感知事件| BT[BehaviorTree]
  Voice -->|语音事件| BT
  BT -->|现有任务服务| Vision
  BT -->|现有任务服务| Voice
  Needs[Emotion / Needs] -->|需求状态| BT
  BT -->|结果与证据| Needs
  BT -->|目标 / 取消| Action
  Action -->|反馈 / 终态| BT
  Action -->|现有航点接口| Nav[waypoint / Navigation]
~~~

这张图表示领域职责；具体消息身份、方向和兼容例外以 interfaces 登记及
[已落地架构自审](../architecture/PLATFORM_IMPLEMENTATION_REVIEW.md) 为准。
工具只装配进程、环境和测试，不新增运行时业务总线或所有模块共同依赖的业务 common。

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
| Action→BT→Needs 结果/证据 | 三模块单测 | check_contracts.py |
| ROS IDL / service / action | 架构和原 IDL 兼容检查 | 生产方/消费方测试、build、doctor、对应 DDS 测试 |
| 进程组合/运行配置 | 平台测试 | 默认 smoke + check_local_lifecycle.py |
| waypoint/Nav2 | 原导航契约 | 可选真实 Nav2 smoke、check_nav2_recovery.py |
| C++/CMake/ROS package | package 依赖 DAG | check_robotics.py 或对应扩展 ROS build/runtime |
| 锁或第三方快照 | 所属独立环境 / 哈希 | 干净安装/编译与许可来源审查 |

当前 CI 按模块分 job，基础架构检查复用 dev.py check。
Humble 集成仅在手动触发的专用 localhost runner 上运行，默认不使用硬件。
由于还没有远端及 runner，已提交的 workflow 只代表配置；本地证据在 validation。
不引入复杂增量 CI 推断：先保证所有模块 job 可独立复现，再按实际耗时优化。

## 历史与第三方

旧仓到新路径和 Git 提交映射在 docs/migration、integration/migration/baseline。
所有新代码以本仓为权威。third_party 管理来源/固定提交，.external 是可重建输出；
RTAB 的本地定制 fork 保留，不能用随手下载的 upstream 覆盖。
模型/构建输出/虚拟环境/设备私有配置不跟随功能 PR 提交。
