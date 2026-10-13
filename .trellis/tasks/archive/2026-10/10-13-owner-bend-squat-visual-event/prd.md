# 主人弯腰／蹲下视觉直驱事件

## Goal

让 Vision 在确认主人持续弯腰或蹲下时，通过现有视觉事件与 BehaviorTree 仲裁链路生成一次互动候选；姿态解除后重新武装。不能把其他人的相同姿态当作主人事件，也不能由 Vision 直接执行动作或改变 Emotion。

## Background and Constraints

- Vision 已发布精确姿态 `bend_over`、`squat_down`；沿用其输出和算法/时序阈值。保持已落地的主人、家人、陌生人事件不变。
- 事件仅适用于同一当前目标的 `identity=owner`、`identity_state=confirmed_known`、`tracking_state=tracking`。
- 首选姿态事件稳定时长 `T_enter=1.0s`。重复发布同一 source observation 的 10 Hz 快照不推进计时。
- GesturePose 已有姿态释放迟滞：10 次更新中 `score >= 0.50` 的支持数低于 3 时释放活动姿态。沿用此有效释放规则，不额外加冷却。
- 保持 `/perception/visual_event`、visual-event schema v1 和现有可选状态字段；不新增 Topic、ROS 类型、required 字段或改写冻结契约基线。
- BehaviorTree 候选只从同快照、同 epoch、仍新鲜的主人目标和姿态上下文创建，并进入现有 L2 多源仲裁。
- 产品候选标签 `ACT_OWNER_APPROACH_RESPONSE` 不是现有登记的 Action unit。代码调查确认可复用的执行映射仅覆盖“靠近主人”：BT `approach_owner` → Action `ACT_INTERACT_APPROACH_OWNER_CLOSER`。该候选不增加尾摆或抬头阶段；现有尾摆/观察类单元在 Lite3 上是未验证代理，不能声称满足这些动作。
- 不修改现有事件语义、身份确认规则、Emotion 映射、姿态算法、导航/避障内部、机器人控制协议、ROS 接口、模型或运行时版本。
- 测试不连接硬件或生产 ROS 域；纯逻辑和真实 ROS transport 证据分开报告，skip 不计为通过。

## Requirements

1. 新增清楚独立的主人弯腰/蹲下视觉事件名，不使用 `ACT_OWNER_APPROACH_RESPONSE` 作为 ROS 事件名。
2. 姿态事件只接受同一个有效当前目标：主人、`confirmed_known`、`tracking`、正数 track ID，目标与 `vision_epoch` 一致；家人、陌生人、未确认身份、失效跟踪、过期或其他目标不得触发。
3. 复用 Vision 当前 `bend_over`/`squat_down` 公共姿态输出，不改模型、推理管线、识别算法或其阈值。以不同且有效的 source observation 推进 1.0 秒稳定时间。
4. 达到稳定时间后创建一个事件上升沿和稳定 event ID。姿态保持期间 `events[]` 持续包含该事件，event ID 不变，不能重复创建候选。
5. 只在同一主人目标的有效 source observation 表明 GesturePose 已按现有 `<3/10` 释放规则解除两种姿态后，移除活动事件并重新武装；之后稳定的新周期允许再次触发。不增加 `T_retrigger=3–5s` 冷却。
6. 相机断流、推理失败、过期数据、无效观测、重复包和短暂恢复不得伪装成姿态解除或让同一事件周期重复触发。目标 ID 或 `vision_epoch` 变化不得将旧周期用于新候选。
7. 复用现有 `events[]`、`observation_status`、`source_observation_id`、`event_instances` 与快照上下文。旧 v1 消费者可忽略可选状态字段。
8. 将新事件加入 BehaviorTree 视觉直驱白名单和映射。候选映射到实际 BT `approach_owner`，其现有 Action 为 `ACT_INTERACT_APPROACH_OWNER_CLOSER`；只实现可验证的靠近反应。姿态事件按现有互动视觉优先级进入统一仲裁，不使用安全最高优先级。
9. 候选携带并复验 event ID、owner target、`vision_epoch`、snapshot/source IDs 和姿态；目标过期、姿态解除、事件周期变化、epoch/track 改变时拒绝未执行候选。
10. 不新增 Emotion 映射或情绪增量；现有主人身份、表情和情绪事件保持原义。
11. 同步更新 Vision、Behavior 与应用视觉事件契约文档，准确说明事件、身份门控、进入/释放规则、快照活动含义、消费者去重、仲裁路径、Behavior/Action 映射和能力限制。

## Acceptance Criteria

- [ ] `EVT_VISION_OWNER_BEND_SQUAT` 仅由 `owner / confirmed_known / tracking` 的同一有效目标产生；熟悉人、陌生人、未确认身份、失效跟踪、过期、目标不一致和跨 epoch 上下文都不能生成主人候选。
- [ ] `bend_over` 或 `squat_down` 的不同有效 source observations 满 1.0 秒后产生一次事件 ENTER；阈值前不触发，重复 source ID 不推进计时。
- [ ] 两种姿态之间切换但姿态周期未解除时保持同一事件实例；HOLD 快照不重复生成候选。
- [ ] 有效同目标姿态输出按 GesturePose `<3/10` 规则释放后，事件从 `events[]` 和 `event_instances` 移除并立即重新武装；再次稳定 1.0 秒后产生新 event ID 和单次候选。
- [ ] 短暂单帧漏检、相机断流、推理失败、无效或过期观测、重复包和短暂恢复不错误释放已活动周期、不重置有效活动 ID，也不重复产生同周期候选。
- [ ] 目标切换或 `vision_epoch` 改变会丢弃旧周期上下文；新目标不能沿用旧姿态计时或 event ID。
- [ ] 新事件通过 visual-event v1 和 BehaviorTree 白名单进入现有候选池及 L2 仲裁；候选绑定同一新鲜 owner/posture 快照；Vision 无 Action 直接调用。
- [ ] 候选映射为 `approach_owner` → `ACT_INTERACT_APPROACH_OWNER_CLOSER`，并服从既有 Action 目标、安全、导航及取消门限；不声称尾摆、抬头观察或复合 `ACT_OWNER_APPROACH_RESPONSE` 已执行。
- [ ] 新事件不改变 Emotion 输出；既有主人、家人和陌生人事件的行为与固定契约结果保持不变。
- [ ] 冻结的 `interfaces/application/visual-event-v1/baseline.json` 未自动更新；纯逻辑、行为映射、视觉契约和命名测试覆盖新事件。
- [ ] `python3 tools/dev.py check`、Vision/Behavior 受影响模块测试、`python3 -B tools/check_visual_contracts.py` 与 identifier 检查结果分别报告；skip 和未运行的 ROS transport 检查明确标示。

## Out of Scope

- 变更或重构已落地的 `EVT_VISION_OWNER_PRESENT`、`EVT_VISION_FAMILY_PRESENT`、`EVT_VISION_STRANGER_PRESENT` 及其 Emotion/身份语义。
- 调整弯腰/蹲下模型、算法阈值、GesturePose smoother、推理频率或通用身份确认规则。
- 新增完整的 `ACT_OWNER_APPROACH_RESPONSE` Action unit、尾部控制或头部观察动作；将未验证代理描述为真机能力。
- 修改 ROS 接口、visual-event v1 必填字段/基线、Emotion 事件映射、需求结算、导航/避障逻辑或硬件协议。
