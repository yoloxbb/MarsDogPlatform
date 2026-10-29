# Visual event v1 兼容契约

端点 /perception/visual_event，ROS 类型 std_msgs/msg/String，Vision 发布、
BT/Emotion/Action 消费；可靠性沿用 BEST_EFFORT，具体配置见原节点。
JSON schema_version 是整数 1。生产规范化仍在
modules/vision/marsdog_vision_interaction/messages/visual_event.py。

| 字段组 | 原有含义 |
| --- | --- |
| header.stamp / frame_id | 感知时间及坐标系；不替换为接收时间 |
| vision_epoch / snapshot_id / sequence | 生产实例与快照标识；重启后不能混用旧目标 |
| active_target / human_candidates | 目标引用、身份、跟踪状态、朝向和距离证据 |
| humans / tracked_objects | 人体和物体观测；不表示行为执行许可 |
| events | 字符串事件序列，保留来源顺序 |
| last_seen_age_ms / tracking_state | 观测新鲜度与跟踪状态；身份不充当 target_id |
| range_valid / distance_m / pose_3d | 原有距离有效性、深度和坐标；未知不能伪装为 0 距离 |

### 统一视觉事件生命周期（v1 可选扩展）

以下 7 个事件共享同一状态生命周期：`EVT_VISION_MASTER`、`EVT_VISION_FAMILY_MEMBER`、
`EVT_VISION_STRANGER`、`EVT_VISION_OWNER_BEND_SQUAT`、`EVT_VISION_MASTER_HAPPY`、
`EVT_VISION_MASTER_SAD` 和 `EVT_VISION_TOY`。每个事件实例可选携带
`event_instances.<event>.lifecycle_state`，取值为 `ENTER`、`HOLD` 或 `EXIT`。`ENTER` 表示
目标稳定出现，`HOLD` 表示状态持续，`EXIT` 表示达到退出条件；EXIT 快照不再把事件放在
`events[]`，但保留该周期 ID 和 EXIT 状态一次。周期内 ID 稳定，下次 ENTER 使用新 ID。

默认共享时序为 `T_enter=1.0s`、`T_exit=2.0s`、`T_retrigger=3.0s`。重复同一源观测不推进计时；
无效、过期或来源不完整的观测不是负检测。各算法原有置信度阈值、身份门控和证据有效性继续生效，
不引入统一置信度阈值。Behavior 对带生命周期字段的事件只在 ENTER 创建直接行为候选，HOLD 不重复
触发，EXIT 不触发；不带该字段的旧 v1 消息继续按既有兼容路径处理。明确携带未知状态值的实例按无效
输入处理，不回退到旧事件名触发。

`EVT_VISION_OWNER_RECALL_GESTURE` 是一个动作型例外：`lifecycle_state=TRIGGER` 只发布一个快照，
同一有效主人目标的现有有效清除证据才会重新武装，不增加状态冷却。它不发布 HOLD/EXIT。

### 主人 MASTER 状态（v1 可选扩展）

`EVT_VISION_MASTER` 将主人和已有资格的已知非家人身份放在一个共享事件周期中；所有来源都经过上述
共同生命周期，且非家人身份保留原事件资格。`owner_greet` 仍要求当前确认主人目标。
已登记家人只走独立的 `EVT_VISION_FAMILY_MEMBER` 事件。`EVT_VISION_OWNER_PRESENT` 已退役，不再发布或消费。此语义调整留在
`schema_version=1`，事件 envelope、required fields 和 ROS 接口不变。

owner MASTER 使用可选字段 `observation_status`、`source_observation_id` 和
`event_instances`：

| 字段 | 语义 |
| --- | --- |
| `observation_status` | `valid` 表示本快照来自新鲜有效推理；`invalid` 表示断流、推理失败或源观测过期。未知值按 invalid 处理 |
| `source_observation_id` | 单个源观测的唯一标识；重复发布同一源观测的 10 Hz 快照不推进稳定计时 |
| `event_instances.EVT_VISION_MASTER.event_id` | 一个聚合 MASTER 周期的稳定 ID；ENTER 后 HOLD 保持，EXIT 快照携带结束 ID；下个 ENTER 使用新 ID |

MASTER 聚合主人和已知非家人身份共享的有效源观测；家人不计入此事件。任一符合身份资格的目标
可以维持同一 MASTER 周期，不会因目标身份变化创建并行实例。活动事件在 ENTER/HOLD 期间留在
`events[]`，经过 2 秒有效连续未识别后发一个带原 ID 的 EXIT 实例并从活动事件集合移除。
无效观测不充当负检测。

Emotion/Needs 沿用已有映射和去重；Behavior 只有收到 MASTER ENTER、有效来源元数据和同快照唯一
`owner / confirmed_known / tracking` 新鲜目标时，才创建 `owner_greet` 候选，并按 event ID 去重；
其它已知非家人身份共享该事件 ID，但不能绕过主人身份门控。短暂 Topic 中断不会清除周期记忆。

固定的 `cases.json` 和 `baseline.json` 保留语义调整前的历史观测字节，不代表新的主人触发
逻辑；常规契约检查仍逐项比较它们。MASTER owner-state 发布、Behavior owner 限定和 Emotion
映射另由独立探针及模块测试验证。

### 主人弯腰/蹲下状态事件（v1 可选扩展）

`EVT_VISION_OWNER_BEND_SQUAT` 是独立的互动姿态事件，消费 Vision 已公开的
`pose_action=bend_over` 或 `pose_action=squat_down`。它不使用产品候选标签
`ACT_OWNER_APPROACH_RESPONSE` 作为 ROS 事件名，不改变主人身份事件、Emotion 事件或视觉接口。

事件进入要求同一当前目标同时满足 `identity=owner`、`identity_state=confirmed_known`、
`tracking_state=tracking`，有正数 `track_id`，且目标 `target_id`、`vision_epoch` 与姿态证据匹配。
家人、陌生人、未确认身份、失效跟踪及仅由 tracker 保留的目标都不能触发主人事件。复用现有身份
确认规则，不添加通用置信度门槛。共享 `vision_event_lifecycle.enter_duration_sec` 默认 `1.0s`；只有
不同且有效的新 `source_observation_id` 推进稳定时间，10 Hz 重复快照不推进计时。

姿态解除沿用 GesturePose 当前公共输出迟滞：最近 10 次姿态更新中至少 6 次分数 `>=0.50`
才公开，活动姿态在支持数至少 3/10 时保持，低于 3/10 时清除。姿态释放后按共享
`T_exit=2.0s` 判断退出，EXIT 快照保留周期 ID 并从 `events[]` 移除；之后按共享
`T_retrigger=3.0s` 冷却并重新完整满足 `T_enter`。弯腰与蹲下之间转换但公共姿态未释放时，
仍为同一活动周期和稳定 event ID。

断流、推理失败、无效/过期输入不会伪装成姿态解除：未完成 ENTER 连续性重置，已活动周期及 ID
保持。若同一 target 在当前源帧中失去主人身份/跟踪上下文，对外事件移除并内部保持 disarmed；
直到该同一当前 source target 的公共姿态清除才重武装。retained-only 目标行不参与退出判断。
目标切换或 `vision_epoch` 改变时清除旧目标状态，新目标重新完整累计 1.0 秒。消费者必须验证
有效 observation、同包事件实例 ID、epoch、snapshot/source IDs、唯一新鲜主人目标和当前姿态，
并在派发前再次验证；事件出现不等于动作已执行。

Behavior 对新姿态事件从每个有效快照（含不带该事件的快照）记录 epoch 与 sequence 高水位；
同 epoch 的回退序号及已经退休的 epoch 不能再创建姿态候选，派发前的缓存必须对应最新接受的
姿态快照。epoch 是不透明标识，因此此保障针对消费者已经见过并退休的 epoch；无法据此排序首次
遇到的未知 epoch。重复的当前快照仍沿用事件实例去重，短暂缓存超时不会丢失周期记忆。

BehaviorTree 将此事件映射为 `owner_approach_response` 意图，并通过既有 L2 候选池及多源仲裁，
使用 BT Behavior `approach_owner`，对应 Action unit `ACT_INTERACT_APPROACH_OWNER_CLOSER`。
目前只确认“靠近主人”执行阶段可复用；尾摆与抬头观察没有匹配且经验证的执行能力，因此不声称
已执行完整 `ACT_OWNER_APPROACH_RESPONSE`。Vision 不直接下发动作，此事件不进入 Emotion 映射。

### 主人招手/挥手召唤（v1 可选 TRIGGER 事件）

`EVT_VISION_OWNER_RECALL_GESTURE` 表示同一当前确认主人目标的一次召唤动作型 `TRIGGER`。
Vision 复用 GesturePose 已有稳定精确内部类别：`beckoning`（招手示意过来）和 `waving`
（挥手）都按产品语义表示召唤。检测器不判断 `waving` 的问候意图，因此所有稳定的 `waving`
分类都触发召唤；静态举手 `arms_raised` 不触发。`waving` 与 `arms_raised` 虽在公开
`pose_action=arm_raise_wave` 中合并，事件使用同一推理结果的稳定 `recognized_actions[]`
区分它们，内部诊断不进入 v1 JSON。

触发要求当前源帧的唯一目标为 `owner/confirmed_known/tracking`，目标仍新鲜有效、track ID 为正，且
手势诊断绑定的 `target_id/track_id` 与其一致。熟悉人、陌生人、未确认身份、失效/过期目标和歧义主人
均不能触发。事件在一个有效主人快照上发布一次 `TRIGGER` 和 event ID，随后从 `events[]` 与
`event_instances` 移除；不发布 HOLD/EXIT，也不增加状态冷却。只有不同、新鲜、有效的同一主人观测
确认两种稳定类别都已解除，且建立该实例的类别/同侧来源当前有效可判定时，才重新武装；静态
`arms_raised` 不阻止解除。私有来源诊断复用 BECKONING 的同侧
有效手部/手指几何及既有 `0.35 s` 连续性，以及 WAVING 的同侧腕/肩关键点有效性；不改变触发类别、
分数或 GesturePose 阈值。重复源观测、10 Hz 快照重复、无效或过期观测、推理失败、相机/Topic 中断、
缺少/歧义手部或腕点证据及缺少当前主人目标都不能充当解除证据。目标或 epoch 切换会使旧实例失效，
并要求新上下文先有一条不同的有效主人清除观测，且旧周期同侧来源可判定，才能重新武装。

BehaviorTree 只在当前有效 v1 快照中按事件 ID 去重，并绑定同包唯一新鲜主人目标；候选进入统一 L2
`external_interaction` 仲裁（rank 3、subpriority 12、`safe_point`），派发前按最新 epoch、事件实例和
目标上下文重验。它不直接控制运动，也不新增 Emotion 映射。产品标签 `ACT_VISUAL_RECALL_APPROACH`
映射为现有链路 `owner_approach_response` → `approach_owner` →
`ACT_INTERACT_APPROACH_OWNER_CLOSER`；目前只有靠近能力，没有登记的“到主人面前并等待互动”阶段。
固定 3 秒 `ACT_BASIC_WAIT` 不代表等待主人互动。

### 家人与陌生人在场状态事件（v1 可选扩展）

`EVT_VISION_FAMILY_MEMBER` 和 canonical 陌生人在场事件 `EVT_VISION_STRANGER` 复用上述活动状态、
`observation_status`、`source_observation_id` 和 `event_instances.<event>.event_id` 规则，
各自维护一个类别级活动周期，并使用共享的 1/2/3 秒时序。家人只由身份属于 `family_member_1..4`、状态为
`confirmed_known` 且正在 `tracking` 的当前源帧目标确认；陌生人只由身份 `unknown`、状态
`confirmed_unknown` 且正在 `tracking` 的当前源帧目标确认。两者都使用共享
`T_enter=1.0s`、`T_exit=2.0s`、`T_retrigger=3.0s`。owner 身份仍只走主人事件。

家人事件是家人身份唯一的公开 presence 事件：家人脸不再产生即时 `EVT_VISION_MASTER`。
Emotion 将 `EVT_VISION_FAMILY_MEMBER` 映射为原家人 MASTER 增量（Joy +25、Excite +15、Calm +10）；
若同一快照同时包含主人 MASTER 和家人事件，这份共用 known-person 增量只应用一次。Needs 收到
家人事件时继续执行既有 `ownerPresent=true` 副作用；owner 本身仍由活动 MASTER 表达。

BehaviorTree 将两个 ENTER 周期分别映射到 `familiar_person_greet` 和 `stranger_observe`
候选，并按 event ID 去重。候选必须绑定同包、同 epoch 且唯一的新鲜目标；缺少或无法唯一
确认目标时拒绝候选。陌生人只在同一在场周期内附加一个 `EVT_VISION_STRANGER_ALERT` 或
`EVT_VISION_STRANGER_FRIEND` 情绪分类事件；二者不创建额外 Behavior 候选。Emotion 有分类事件时
只应用分类映射，避免同一快照重复应用陌生人情绪增量。
这两个 Behavior 当前没有 Action 模板，因此候选被记录或排入仲裁不代表歪头、摇尾、注视、
保持距离或警觉动作已执行；Action 会沿现有 unsupported-template 边界拒绝它们。

### 看见玩具状态事件

`EVT_VISION_TOY` 表示场景中至少有一个稳定可见的受支持玩具。已有手持玩具也属于这个状态；
原 `active_target.held_object` 诊断数据继续保留，但 `holding_toy` 不再绕过玩具稳定计时单独
生成一个事件。玩具标签只复用 Vision 现有 Provider 中的 `dog toy ball`、`dog frisbee toy`、
`dog tug ring toy`，不把狗粮或其他物品扩展为本事件。

事件只消费原有物体检测任务的结果和该任务已有的置信度门限。不同、有效且新鲜的源物体观测
推进共享状态时序：默认 `T_enter=1.0s` 后 ENTER；HOLD 保持同一
`event_instances.EVT_VISION_TOY.event_id`；成功、有效且标签范围覆盖全部三类玩具的负观测持续共享
`T_exit=2.0s` 后 EXIT 并移除活动事件，EXIT 实例保留原 ID 一次；之后按共享 `T_retrigger=3.0s`
冷却并完整重新满足 `T_enter`。多框、多个玩具和重复 10 Hz 快照都按一个场景状态处理，不按框重复触发。

只有事件周期会产生一次 Behavior 候选；HOLD 快照不会重复生成候选。Emotion 沿用
`EVT_VISION_TOY` 原有 Excite +30、Curious +20、Joy +15 映射，并按事件 ID 对每个周期只处理
一次。检测失败、相机断流、过期结果、无效快照和不能覆盖全部玩具标签的空结果均表示观测未知，
不能推进 EXIT；未知输入打断未完成的进入/退出连续计时，活动事件 ID 保持。

检测激活方式不因该事件改变。标准 Vision 配置常规物体推理为 0 Hz；受限手持流仍是在有人被跟踪
时以 2 Hz 运行。已有一次性/持续检测会话也可提供观测，但没有人物跟踪且没有其他活动检测会话时
不会有玩具检测输入，因此不能自主发现玩具。

Behavior 将 ENTER 映射为物品类 `external_interaction` 候选，并经统一 L2 仲裁路由至已有
`inspectFamiliarPlayItem`。`ACT_TOY_FOUND_PLAY` 是候选产品标签，不是 Action `unit_id`。该行为
需要 Action 绑定当前新鲜玩具目标并先通过 `ACT_APPROACH_VISUAL_TARGET`；现有视觉物体数据若只有
二维框且没有有效米制范围，接近会按 Action 当前策略 fail closed。事件或候选不代表靠近、嗅闻、
叼取或玩耍已经执行成功。

Vision 可在当前检测人脸及 `debug_faces` 中附加可选字段
`facial_expression: {expression, confidence}`。`expression` 是模型八类结果之一，
`confidence` 是胜出类别原始 softmax 概率；调试快照可带
`facial_expression_valid_for_sec` 表示该结果剩余有效期。这是人脸表情证据，
不表示或更新 MarsDog 的 `/emotion/state`。该字段为 schema v1 的可选扩展，
不改变既有 required 字段及冻结基线。

`EVT_VISION_MASTER_HAPPY` 和 `EVT_VISION_MASTER_SAD` 也是上述 7 个持续状态事件的一部分，
分别使用已有 happy/sad 算法证据及来源有效性门控，再按共享 ENTER/HOLD/EXIT 时序发布。
任一适用来源的有效正证据都可维持事件；只有所有适用来源都持续给出有效负证据才累计退出时间。
缺失、过期或置信度不足的来源属于未知，会打断待进入/待退出连续计时，但不会结束已有周期。
当前有效目标是家人或已确认陌生人时，主人专用的面部来源不适用，不阻止姿态来源的正常退出；
曾支持该事件的主人面部来源在随后缺失时保持未知，不能因旧表情来源释放计时结束而变成负证据。
各自原 Emotion 映射和事件去重规则不变；短于 `T_enter` 的证据不会产生状态 ENTER。

姿态/手势正式事件仅在目标处于 `tracking` 时发布，并要求身份满足以下其一：
登记身份 `owner` / `family_member_1..4` 且 `identity_state=confirmed_known`，或
`identity=unknown` 且 `identity_state=confirmed_unknown`。已确认陌生人的姿态继续使用
现有 v1 事件名；未确认、候选和失踪目标仍受门控。由此产生的 FALL/STOP 事件会沿用
行为树现有直接事件规则。

BT 严格要求整数版本和字符串事件数组，再更新原场景缓存。
直接事件 EVT_VISION_FALL / EVT_VISION_STOP_GESTURE 沿用出现边沿去重，缓存超时后重新判边；
STRANGER 通过上述带实例 ID 的在场事件路由进入候选池。
目标有效性和服务降级仍由原规则决定。消费者回调在缓存锁外调用。
缺少 human_candidates 时只在 epoch 和有效 track_id 存在时构造兼容目标。

Emotion 按已有感知适配器选择事件并更新领域状态，不复用 BT 执行权限逻辑。
Action 的 JSON 分发对损坏或非 object 消息向运动相关适配器传空快照，保留失效停止路径；
不会把“解析失败直接返回”推广为所有消费者的共同策略。

本轮刻意保留已有消费者差异：例如 humans=null 等部分结构错误可能在 BT 更新部分接收信息后
抛错；兼容基线记录该异常，不把它伪装成成功或顺便改变其行为。身份门控语义由
`c8f73d2` 扩展；固定样例覆盖已确认陌生人的姿态事件。负例不构成推荐生产格式。

`python3 -B tools/check_visual_contracts.py` 验证 8 组真实 Vision 规范化输出及
34 个序列场景：身份/目标、空帧、边沿重复/消失/重现、超时、错误版本/类型、
坏 JSON 和多个消费者的不同容错。基线在 66c7eaa 修改前采集。
固定时钟与随机种子，候选仅去除随机 candidate_id/created_at；保留内容、顺序、
缓存、状态、副作用和异常。无 DDS/模型/相机；DDS 由单独的本机 smoke 验证。
