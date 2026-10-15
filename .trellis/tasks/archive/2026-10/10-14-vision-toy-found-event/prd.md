# 实现视觉直驱玩具发现事件

## Goal

当现有视觉物体检测路径稳定识别到视野中的玩具时，发布一次状态型 `EVT_VISION_TOY`，使 Behavior 产生一次可参与统一仲裁的玩耍候选，并按既有玩具规则影响 Emotion 一次。

## Confirmed repository behavior

- `/perception/visual_event` 是 `std_msgs/msg/String` 承载的 schema v1 JSON 状态快照，约 10 Hz；`events[]` 为字符串数组。契约已支持可选 `source_observation_id` 和 `event_instances`，本任务不需要改 required fields 或冻结基线。
- 当前 `EVT_VISION_TOY` 由 `holding_toy` 姿态路径产生并受人物确认/跟踪门控；因此当前生产语义实际上是手持玩具，不覆盖普通可见玩具。Emotion 已将它映射为 Excite +30、Curious +20、Joy +15。
- 当前物体 Provider 使用的玩具标签为 `dog toy ball`、`dog frisbee toy`、`dog tug ring toy`，定义于 held-object 代码中的玩具标签集合；本任务只复用这三类。
- 标准 `vision.yaml` 的物体 Provider 延迟加载，常规推理频率为 0 Hz。受限手持物体流只在有人被跟踪时以 2 Hz 启动；独立 object-only 调试配置的 1 Hz 常驻流不是标准运行配置。
- Vision 已将物体检测结果及其状态、帧/结果序号、来源和时间戳写入缓存；Behavior 有视觉事件订阅、候选池及 L2 仲裁，但当前视觉直驱白名单没有 `EVT_VISION_TOY`。
- Action 已登记 `inspectFamiliarPlayItem`：先尝试 `ACT_APPROACH_VISUAL_TARGET`，再从已有忽略、叼咬摇晃、扑、携带、拍碰、嗅闻单元中选择。现有物体目标通常没有有效米制深度；Action 接近策略要求真实目标范围，不能从二维框推算距离。

## Scope

schema v1 顶层 `observation_status` 沿用当前视觉/人体观测语义，不是物体检测的独立有效性标记；玩具状态以物体 Provider 结果和物体目标新鲜度为准，不能因无人身份/人体观测状态而被门控。

- 使用现有检测结果生成场景级玩具存在状态，接入视觉 v1、Behavior 视觉直驱候选、既有 Emotion 映射。
- 保留手持玩具相关 `held_object` 数据，并让手持玩具共用同一 `EVT_VISION_TOY` 状态周期。
- 补充 Vision、Behavior、Emotion、契约测试及对应文档。

## Out of scope

- 狗粮、牵引绳、项圈或其他物品事件；人员身份门控；新模型/标签/权重/provider；改变单次、持续或手持检测配置和频率。
- 新 ROS topic/type、v1 required field、冻结契约基线改动；由 Vision 选择最终动作；依据二维框制造三维目标或执行成功。
- 无人被跟踪且没有其他现有物体检测会话时的自主玩具发现。该限制由现有标准检测激活配置决定，并经用户确认保留。

## Requirements

1. 复用 `dog toy ball`、`dog frisbee toy`、`dog tug ring toy` 三个已有标签及各检测任务自己的置信度阈值，不增加跨算法阈值。
2. `EVT_VISION_TOY` 表示稳定可见玩具，手持玩具是其子集；旧 `held_object` 数据和 Emotion 映射保留。不可新增并行的玩具事件。
3. 按场景级“至少一个有效玩具存在”计状态，不按检测框或玩具数量拆分事件。不同、新鲜、有效物体观测推进稳定时间；重复源观测不推进。
4. `T_enter=1.0s` 后只 ENTER 一次；HOLD 保持同一事件实例且不再产生候选；有效完整标签范围观测持续未检出玩具 `T_exit=2.0s` 后 EXIT；EXIT 后 `T_retrigger=3.0s` 冷却结束前不得再次 ENTER，之后仍须重新满足完整 `T_enter`。三个值可配置。
5. 有效负观测必须来自成功且新鲜、覆盖全部玩具标签的物体检测结果。标签过滤未覆盖全部玩具类、物体推理失败/过期、无效物体结果或相机断流是未知，不得推进 EXIT；未知也不得补足 ENTER。Behavior 不将顶层人体 `observation_status` 当作玩具资格门控，仍需在同一快照绑定新鲜玩具目标。
6. 只让首次事件实例进入 Behavior 候选池；使用现有物品类 L2 仲裁和实际登记的 Behavior/Action 能力。`ACT_TOY_FOUND_PLAY` 是候选产品标签，不得冒充现有 Action `unit_id`。
7. Emotion 沿用既有玩具增量，以事件实例 ID 对每个周期只应用一次；重复 HOLD 不叠加。没有实例 ID 的旧 v1 载荷保留原兼容处理。
8. 沿用 `/perception/visual_event` 与 schema v1；保持其它人物、姿态、手势、跌倒和 Stop 事件语义。

## Acceptance criteria

- [x] `T_enter` 前不发布玩具事件；达到阈值时产生唯一事件 ID 和一次 Behavior 候选。
- [x] HOLD 保持同一 `EVT_VISION_TOY.event_id`，不重复候选或 Emotion 增量。
- [x] 连续有效负观测少于 `T_exit` 保持事件；达到 `T_exit` 后 EXIT 且不产生候选。
- [x] EXIT 后冷却内不重触发；冷却结束后必须重新满足 `T_enter`。
- [x] 重复观测、重复框、抖动、多个玩具和 10 Hz 快照不按帧/框触发。
- [x] 断流、无效/失败/过期推理和不完整标签范围的负结果不被当作玩具消失；未知不能完成 ENTER。
- [x] 不手持且无身份信息的玩具，只要被现有有效检测流识别并稳定存在，就能产生同一事件；原手持数据及玩具 Emotion 映射保留。
- [x] 新候选通过现有候选池和 L2 仲裁；缺少真实 Action 目标几何时不得报告执行成功。
- [x] 既有主人/熟悉人/陌生人、姿态、手势、跌倒和 Stop 事件行为不回归。
- [x] Vision、Behavior、Emotion（如需映射说明）、visual-event 契约文档与纯逻辑/契约测试完成。
- [x] 运行仓库 check、受影响模块测试与 `python3 -B tools/check_visual_contracts.py`；纯逻辑、真实 ROS transport、skip 分开报告，skip 不记为通过。

## Technical decisions and limits

- 用户指定复用 `EVT_VISION_TOY`，并接受把其公共语义从“确认手持玩具”扩展为“稳定可见玩具”；实现以单一场景状态机发布该事件，避免旧手持生产路径与新视觉路径双发。
- 用户选择保持现有检测激活策略。标准配置仍是 0 Hz 常规推理，既有 2 Hz 手持流仍要求有人被跟踪；没有人跟踪且没有其它检测会话时没有观测输入，无法自主发现玩具。事件实现不改变该资源/产品决策。
- 未按 `target_labels` 请求覆盖全部三个玩具类别时，正命中已支持玩具仍可作为正观测；空结果不是完整负观测。所有状态时序只按新鲜、不同的源图像/观测标识推进。
- 目标框不提供可用距离时，候选仍受现有 Action 安全边界约束；接近阶段可以 fail closed，不能宣称完成靠近、嗅闻、叼取或玩耍。
