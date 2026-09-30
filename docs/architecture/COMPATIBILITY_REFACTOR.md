# 五模块兼容性整合重构

用户于 2026-09-30 授权在保留原始功能的前提下持续完成五模块重构。
**R1–R4 均已完成。** 主仓迁移不重复；导航/避障内部、模型精度与设备协议不在本轮范围。
证据见 [R2–R4 验证](../../validation/compat-refactor/r2-r4/README.md)，
R1 原证据保持在 validation/compat-refactor/r1。

## 最终边界

| 模块 | 已拆出的职责 | 保留的领域权威 |
| --- | --- | --- |
| Voice | interaction_session、speech_pipeline、task_router、messages/task_service | 会话/hold、ASR/声纹/意图协作、KWS 权限与事件顺序 |
| Vision | visual_snapshot、visual_event_derivation、task_router、messages/task_service | 感知/跟踪/身份/目标引用、深度和模型计算 |
| Emotion / Needs | common/state_publication 共用发布机械逻辑 | 情绪/需求数值、阈值、时间窗口与结果结算 |
| BehaviorTree | audio_contract、visual_event_consumer、state_subscriptions、voice_engagement | 缓存、候选、恢复、仲裁、抢占、语音会话与异步代次 |
| Action | perception_dispatch、goal_contract、action_messages、goal_lifecycle、goal_execution | 预约/lease、执行阶段、取消终态、资源归属与控制门限 |

ROS 节点继续负责参数、资源、订阅/服务/Action 装配以及生命周期入口。
旧方法保留代理，既有调用方和测试入口不用改名。协调函数的 self 是由节点提供的
原上下文端口：继续使用同一锁、会话、候选池、provider 和 adapter，不复制第二份状态。
可替换时钟、消息工厂、枚举、日志与异步协作者由原入口注入；
新组件可在无 ROS 的独立 wheel 中导入，不能反向 import ROS 节点或其他领域业务。

节点仍可包含较长的装配代码；本轮完成标准是可验证的职责边界和原功能一致性，
不是把所有行搬出节点，也不是重写全部算法。60 个提取函数的主体已和
66c7eaa 的 AST 比较一致（仅列明的依赖注入替换）；Emotion 发布共用化由实际
发布路径测试及冻结状态契约验证。

## 公共协议与公共模块

[应用协议目录](../../interfaces/application/README.md) 统一查阅字段、所有权、
错误语义、固定样例和验证命令；interfaces/registry.json 与 ROS IDL 保持原身份。
tools/contract_harness.py 与 integration/contracts/worker_support.py 只共用测试编排。
Emotion 的 common/state_publication 只在 Emotion 领域内复用。

没有建立第二套总线、总控 RobotState 或跨领域业务 common。
VoiceTask/VisionTask 的字段相同，类型和 trace 语义仍不同；
audio、visual、state 版本字段也不同。各消费方的原有容错差异进入基线，
不通过统一严格解析器悄悄改变协议。waypoint 的历史类型依赖保留给负责人。

## 完成切片

| 切片 | 已交付 |
| --- | --- |
| R1 声音 | audio v2 固定契约、46 场景、BT 无状态校验；原提交 66c7eaa |
| R2 视觉 | 7 组生产数据、33 场景；视觉快照/目标查询/事件派生、BT 缓存消费、Action 分发 |
| R3 状态与动作 | 7 组状态生产序列、34 场景；发布共用、BT 权威状态消费；Action 请求/反馈/终态与执行协调；保留 25 项结果契约 |
| R4 职责拆分 | Voice 会话/识别/任务、Vision 任务、BT 语音协调；每端 18 项任务服务观测；五模块全量回归和安装验证 |

冻结输出先于对应运行时代码修改采集。正常门禁只读 baseline.json，
不提供自动更新选项。所有阶段在所属环境和进程运行，校验源码来源、虚拟环境、
跨领域导入及 ROS 可见性；失败不能保留旧 PASS，空基线不能通过。
新的 14 项平台测试覆盖这些失败路径与组件依赖方向。

## 本轮验证

- 平台 71 项通过；五模块原全量测试通过：Voice 430，Vision 289 + 3 RGA skip，
  Emotion 218 tests + 156 subtests，BT 533，Action 423 + 29 skip。
- Action 的 20 个 ROS 环境跳过项由专门的 35 项真实回调测试覆盖，0 skip；
  剩余 9 项为 PySide2 GUI，不能算通过。
- 音频 46、视觉 33、状态 34、任务每端 18、结果 25 契约全部保持。
- 五个隔离 wheel 安装通过；18 个组件导入及 SHA256 与源码一致，无 ROS 节点反向导入。
- 默认 ROS 15 包增量构建、doctor、安装节点 smoke、DDS 取消归属、
  SIGINT/SIGTERM 停止后退出、中断/异常传播/重复启动/PID 回收通过。
- 286 个受保护文件字节未变，覆盖配置/锁/IDL、原模型适配器、导航与第三方登记。

ROS smoke 的感知、导航、设备使用原模拟组合；没有摄像头/麦克风/NPU/实机验收，
没有模型精度优化，也没有 hosted CI 运行。新增 workflow 已做本地等价命令验证。
旧 P7 源码包与验收仍对应 2468639/3f50614；此次未重新打包旧交付目录。
后续按实际功能需求开发；远端治理、板端、设备验收依赖相应外部事实。
