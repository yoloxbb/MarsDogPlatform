# 五模块兼容性整合重构

用户于 2026-09-30 授权按此方向推进。主仓迁移与开发交付已完成，
本阶段以保留原始功能为前提整理接口和模块边界。导航/避障内部实现留给负责人，
本阶段仅保留其已登记外部接口；模型精度、依赖升级和硬件协议均不在本轮范围。

## 审查结果与责任边界

| 模块 | 现有边界与实现位置 | 可提取内容 | 留在领域内的内容 |
| --- | --- | --- | --- |
| Voice | messages/audio_event.py、messages/intent_event_router.py、core/command_lexicon.py、nodes/voice_interaction_node.py | 消息构造与 ROS 收发装配分离；集中跨模块契约样例 | ASR/意图路由、会话、声纹、执行权限生成 |
| Vision | messages、core 与 nodes/vision_interaction_node.py，visual_event 和 VisionTask | 事件与任务应答边界；下一步先冻结生产/消费样例 | 模型后端、跟踪、身份与视觉任务计算 |
| Emotion/Needs | marsdog_ros2/perception_adapter.py、common/json_message.py，marsdog_core | 已有传输适配较清晰；补消息契约与输入兼容测试 | 情绪/需求权威、时间窗口、结果结算 |
| BehaviorTree | perception_client_adapter.py、intent_mapper.py、ros_node.py | 无状态协议校验先拆出；后续按会话/ROS 装配边界拆分 | 仲裁、优先级、抢占、会话状态、候选与证据映射 |
| Action | ros_node.py、适配器与动作执行器 | action 请求/反馈/终态封装，阶段执行与 ROS 装配分离 | 技能阶段、取消终态、资源归属和运动执行门限 |

实际公共面已有 interfaces/registry.json、ROS IDL、外部能力说明，以及
Action→BT→Needs 独立进程结果契约。不能再次建立第二套消息总线、总控 RobotState
或各模块共同依赖的业务 common。VoiceTask/VisionTask 字段相似，但 ROS 类型身份不同；
waypoint 对 VoiceTask 的历史依赖保持原样，交由对应负责人处理。

## 按边界递进

1. **R1 声音链路**：集中 audio v2 文档/样例；冻结 Voice→BT/Emotion 结果；
   抽出 BT 无状态声音校验，保持原调用入口、日志、时钟与副作用顺序。
2. **R2 视觉链路**：冻结 visual_event→BT/Emotion/Action 的正反样例；
   梳理帧/目标/身份/时间戳及任务错误语义，证明一致后再提取各模块 codec。
3. **R3 状态与动作结果**：在已有 25 项结果契约基础上覆盖 Emotion/Needs 发布到 BT、
   ExecuteBehavior goal/feedback/result/cancel，严格保留终态和需求结算。
4. **R4 节点拆分**：每次仅一个有清晰职责的子组件；先增加特征测试，
   将 ROS 装配与可独立验证的领域逻辑分开。节点行数不是验收目标。

每步完成单测、独立环境契约、涉及安装的 wheel 检查与必要的 ROS 回归后再进入下一步。
当前已实现 R1；R2–R4 是后续切片，不记为已完成的五模块重写。

## R1 实现

- 公共契约：interfaces/application/audio-event-v2，46 个固定消费场景。
- 独立进程测试：integration/contracts/audio_stage.py、tools/check_audio_contracts.py。
- BT：marsdog_behavior/audio_contract.py 收纳原 intent_mapper 的无状态权限/槽位校验
  和原节点的唤醒校验。原私有方法保留代理入口；候选、会话、emotion、仲裁均未移入公共层。
- CI 为声音契约增加独立 job；五模块独立环境、IDL、依赖锁和业务配置均保持原值。

不能直接共用严格解析器：Voice 负责规范化完整消息，BT 负责执行权限和关联，
Emotion 兼容旧事件并按自身规则更新状态。容错差异已列入
[audio 契约](../../interfaces/application/audio-event-v2/README.md)，以后改变属于语义变更。

## 验证与限制

本轮的实际命令、状态、测试计数和限制记录在 validation/compat-refactor/r1。
原 P7 验收证据和源码包仍对应 2468639/3f50614，不因本轮新增源码而被覆盖或
误称为最新源码交付包。尚无远端 CI 运行记录；本机 ROS smoke 使用既有隔离模拟组合。
