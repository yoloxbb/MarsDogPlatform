# 主人招手/挥手召唤视觉事件

## Goal

当已确认主人完成现有 GesturePose 检测器识别的招手或挥手动作时，Vision 发布一次有目标绑定的视觉事件；BehaviorTree 将它作为互动候选送入现有多源仲裁，并复用已登记的主人靠近阶段。

## Confirmed facts

- GesturePose 稳定输出 `recognized_actions[]` 中的精确类别 `beckoning`、`waving` 和 `arms_raised`。`beckoning` 的公开兼容值是 `pose_action=beckoning`；`waving` 与静态举手 `arms_raised` 折叠为 `pose_action=arm_raise_wave`。精确稳定类别已由同一推理结果的内部 `_gesture_diagnostics` 保留，Vision 可在组装 v1 事件前读取，不需读取 raw score 或改动公开契约。
- 现有 `beckoning` 检测要求同一只手完成多指屈伸循环，`waving` 表示手臂举起后做连续往返挥动，`arms_raised` 是保持的静态举手。用户已确认招手和挥手都表示召唤：稳定分类为 `beckoning` 或 `waving` 时都触发；静态 `arms_raised` 不触发。分类器不区分动态挥手中的问候意图，因此任何稳定的 `waving` 输出均按本产品语义处理。
- `/perception/visual_event` 保持 `std_msgs/msg/String`、JSON `schema_version=1` 和当前字段；有效观测、源观测 ID、视觉 epoch、快照 ID 与事件实例 ID 已是可选 v1 扩展。
- Vision 已有 `EVT_VISION_OWNER_BEND_SQUAT` 状态事件；Behavior 对该事件执行主人/目标/新鲜度门控、实例去重和 epoch/快照重验。弯腰/蹲下、主人身份及其他视觉事件的语义保持不变。
- 当前可复用链路是 `owner_approach_response` → Behavior `approach_owner` → Action unit `ACT_INTERACT_APPROACH_OWNER_CLOSER`。该 Action 绑定新鲜人体目标并导航到安全停靠距离。仓库另有 `wait_in_place` / `ACT_BASIC_WAIT`，但它是固定时长的原地等待（Action 配置为 3 秒），没有与主人互动事件关联，也没有已登记的主人靠近后互动等待流程。
- 产品候选名 `ACT_VISUAL_RECALL_APPROACH` 不是当前登记的 Action ID。它只能作为产品侧别名映射到上述实际 Behavior/Action 链路，不作为 ROS 事件名或新增执行 ID。

## Requirements

- 使用独立事件名 `EVT_VISION_OWNER_RECALL_GESTURE`，其语义表示已确认主人的 `beckoning` 或 `waving` 召唤手势。
- 仅当前源帧中 `owner / confirmed_known / tracking` 的唯一主人目标可触发；目标、手势、epoch 和源观测必须属于同一当前目标与有效视觉快照。
- 复用分类器的稳定 `recognized_actions[]` 类别及其既有阈值、时序确认；接受 `beckoning`/`waving`，排除 `arms_raised`，不添加 confidence 或额外进入时序。
- 每个连续手势周期只发布一个事件实例并产生至多一个候选。有效新观测确认该同一主人目标的稳定 `beckoning` 与 `waving` 类别均已解除，且建立实例的动作类别/同侧来源当前有效可判定后，才允许重新武装。重复快照、短暂手部/腕点漏检、无效几何、来源连续性中断、无效/过期观测、推理失败、相机断流、Topic 中断、单纯目标切换或 epoch 改变都不能伪装成有效解除。
- BehaviorTree 在新鲜度、唯一主人目标、实例 ID、snapshot/source ID 和 epoch 校验通过后创建候选，放入既有 L2 `external_interaction` 多源仲裁，不直接调用 Action 或运动控制。
- 新候选按现有互动手势/姿态仲裁配置进入统一候选池；不调整全局优先级，不新增 Emotion 映射或情绪增量。
- 更新 Vision、Behavior 与应用视觉事件契约，记录事件周期、失效观测、仲裁路径及实际 Action 能力边界。

## Acceptance criteria

- [ ] 主人、有效跟踪、同一目标和有效新源观测是触发必要条件；熟悉人、陌生人、未确认身份、目标失效/过期、歧义目标均不能触发。
- [ ] 事件仅由同一当前目标稳定识别出的 `beckoning` 或精确类别 `waving` 派生；`arms_raised`、静态举手和其他类别不触发。按用户确认，`waving` 类别即表示召唤，系统不尝试区分问候意图。
- [ ] 连续的多个视觉快照只产生一个稳定事件实例和一个候选；只有有效观测确认同一目标的 `beckoning` 与 `waving` 均已解除，且建立实例的动作类别/同侧来源有效可判定后，新的召唤才生成新实例。
- [ ] 短暂手部/腕点漏检、无效几何、同侧连续性中断、重复源观测、Topic 中断、相机断流、推理失败、无效或过期数据不会产生事件、错误解除实例或提前重新武装。
- [ ] 目标切换或 `vision_epoch` 变化不会将旧目标、事件实例或缓存上下文用于新候选；派发前再次验证当前同 epoch 的新鲜主人目标。
- [ ] 新事件映射到既有候选池与 L2 仲裁，不直接下发动作、不影响 Emotion；现有主人身份、弯腰/蹲下、跌倒和 Stop 行为保持不变。
- [ ] 文档明确映射 `ACT_VISUAL_RECALL_APPROACH` → `owner_approach_response` → `approach_owner` → `ACT_INTERACT_APPROACH_OWNER_CLOSER`，并说明现有固定 3 秒 `ACT_BASIC_WAIT` 不是主人互动等待阶段。
- [ ] `python3 tools/dev.py check`、Vision/Behavior 受影响纯测试和 `python3 tools/check_visual_contracts.py` 通过；纯逻辑与真实 ROS transport 结果分开，skip 不计为通过；冻结基线不自动更新。

## Out of scope

- 修改 GesturePose 模型、推理、识别算法、阈值或运行配置。
- 更改现有主人身份、主人在场、弯腰/蹲下、陌生人、跌倒或 Stop 语义。
- 修改 `/perception/visual_event` Topic、ROS 类型、schema_version 或 required 字段。
- 新增 Emotion 映射、导航/运动实现，或未经定义的“等待互动”Action 阶段。

## Planning status

- 已检查仓库约定、Vision 迁移记录、视觉 v1 契约、Behavior/Action 映射与最近已归档的 beckoning 检测任务；已确认 `waving` 的精确稳定类别可从既有内部推理结果读取，静态举手可排除。
- 产品语义已按用户补充确定：稳定 `beckoning` 与动态 `waving` 都是召唤。分类器不能区分动态挥手的问候意图，事件按上述类别语义执行；静态举手不会触发。
- 现有 Action 覆盖靠近阶段，固定时长原地等待不能替代互动等待阶段。
- 用户已于 2026-10-14 确认最终规划，任务现进入实施阶段。
