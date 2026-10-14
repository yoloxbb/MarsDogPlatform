# 实施与验证计划

## 1. 实施前

- [x] 用户批准最终规划摘要后，进入 Trellis `in_progress` 并读取 `trellis-before-dev` 的 Vision、Behavior 约定。
- [x] 复核工作区状态；保留现有主人身份、主人在场、弯腰/蹲下和安全事件实现。
- [x] 检查 `interfaces/naming` 事件命名登记方式及视觉契约冻结 baseline 的生成/比较边界。

## 2. Vision 事件生产

- [x] 新增独立 owner recall-gesture 状态机；读取同一源观测的稳定 `_gesture_diagnostics.recognized_actions[]`，`beckoning` 和精确 `waving` 触发，`arms_raised` 排除；未改模型、关键点推理、检测决策、分类阈值、时序规则或运行配置；在 `gesture_pose_engine` 增加仅供事件解除校验使用的来源有效性元数据。
- [x] 实现同一有效主人目标 ENTER/HOLD/EXIT、稳定 `event_id`、source observation 去重、失效观测保留和仅有效解除后重武装。
- [x] 将事件接入现有 `/perception/visual_event` producer 的 `events[]`、`event_instances[]` 与现有有效性字段。
- [x] 为状态机和 producer serialization 补纯逻辑测试；保护现有 owner presence/posture/fall/stop 测试。

## 3. Behavior 仲裁

- [x] 将 `EVT_VISION_OWNER_RECALL_GESTURE` 加入 direct visual event allowlist/config 和 owner target qualifier。
- [x] 复用 owner instance ID 去重、同快照唯一目标、新鲜度、epoch/snapshot/source 高水位和派发前二次校验；确保重复 HOLD 快照不重建候选。
- [x] 将事件映射到现有 `owner_approach_response` → `approach_owner` 候选；保留 L2 `external_interaction`, `semantic_rank=3`, `sub_priority=12`, `safe_point`，不增加 Emotion 路由或直接 Action 调用。
- [x] 补候选池/统一仲裁链路与旧事件兼容纯测试。

## 4. 登记与文档

- [x] 登记 `EVT_VISION_OWNER_RECALL_GESTURE` 并通过标识检查；不将 `ACT_VISUAL_RECALL_APPROACH` 用作 ROS event 或 Action unit。
- [x] 更新 Vision ROS2 事件契约/接口 manifest、Behavior 事件对照与能力限制、应用 `visual-event-v1` 契约；区分固定 3 秒通用 wait 与互动等待能力。
- [x] 说明检测类别、owner gate、一次 TRIGGER/解除重武装、无效观测、事件快照与实例去重、L2 路径、Action 靠近阶段及缺少等待阶段。
- [x] 检查 Emotion 和冻结基线；Emotion 输出不变，冻结 baseline 未更新；新增召唤契约探针保持为独立兼容检查。

## 5. 验证

- [x] `python3 tools/dev.py check`
- [x] `python3 tools/dev.py test vision`
- [x] `python3 tools/dev.py test behavior`
- [x] `python3 -B tools/check_visual_contracts.py`
- [x] 运行定向状态机/真实 GesturePose 来源状态回归并记录 passed/failed/skipped。
- [x] 不连接硬件或生产 ROS domain。未运行真实 ROS transport；Vision 3 个 RGA 专用项明确 skip。
- [x] 审核 git diff、既有视觉事件行为、命名登记和 Action 映射；未改冻结 baseline。

## 6. 召唤类别契约用例

- [x] 稳定 `beckoning` 和精确稳定 `waving` 都可触发同一召唤事件；`waving` 与 `beckoning` 连续交替不产生第二个实例。
- [x] 静态 `arms_raised`、无 accepted 类别以及其他动作不触发；确认只消费稳定 `recognized_actions[]`，不依赖 raw score/confidence。
- [x] 记录并测试产品语义边界：用户确认分类器的 `waving` 类别均视为召唤；当前模型/类别不区分动态挥手问候意图，因此不把 `waving` 问候样本作为负例。

## 回滚边界

- 新事件状态机、路由配置、登记与文档可独立撤回。
- 不修改 gesture detector、Motion/Nav2 实现、Action 定义、ROS IDL、schema required 字段或默认算法配置。
- 若 Vision/Behavior event contract 出现兼容性偏差，停止扩散到运行时映射；先收敛 additive v1 事件和可选实例元数据的契约。
