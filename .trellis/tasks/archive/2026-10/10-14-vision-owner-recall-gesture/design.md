# 技术设计：主人招手/挥手召唤视觉事件

## 边界与数据流

1. Vision 复用 GesturePose 单次稳定结果中的 `_gesture_diagnostics.recognized_actions[]` 精确名称，接受 `beckoning` 与 `waving`，排除 `arms_raised`；不读取 confidence/raw score、不重新执行分类、不新增阈值。该字段仅供 Vision 内部消费，保持现有 ROS 事件 schema 不变。
2. 新增 Vision 侧主人召唤事件状态机，读取同一有效源观测内的主人目标、稳定精确类别、`vision_epoch` 和 `source_observation_id`。精确类别须来自与源观测 `active_target` 同一跟踪目标的分类结果，且该目标须与构建出的当前事件快照目标一致。事件名为 `EVT_VISION_OWNER_RECALL_GESTURE`。
3. 首个满足主人门控且稳定类别为 `beckoning` 或 `waving` 的有效源观测触发一次 ENTER，分配唯一 `event_id`。同一连续手势内即使从 `beckoning` 切换成 `waving`，只要接受类别集合仍非空，就保持同一实例；`events[]` 与 `event_instances[event].event_id` 在周期后续状态快照中保持，作为 v1 承载一次 TRIGGER；Behavior 按实例 ID 只消费一次。
4. 仅新鲜、有效、不同源观测中的同一当前主人目标，在 GesturePose 稳定输出确认 `beckoning` 和 `waving` 均已解除，且建立实例的同侧来源当前有效可判定后才能 EXIT 并重新武装。私有来源诊断只复用既有左右手关联、手指几何、`0.35 s` beckoning 连续性和 WAVING 腕/肩关键点有效性；不得改分类分数或阈值。无效观测、手/腕漏检、无效几何或来源连续性中断保持活动实例，不创建新候选或解除；目标身份/跟踪丢失、目标切换或 epoch 改变时撤下与旧目标绑定的对外事件并保留 disarmed 状态，必须等待当前主人目标的有效释放观测，缺失数据不能解除。
5. Behavior 将事件加入视觉直接事件允许映射和主人目标资格规则。候选绑定同一快照唯一主人目标、epoch、snapshot/sequence、source ID 与事件实例 ID；重复快照由实例去重，候选构造与派发前都重验观测有效性、目标新鲜度和当前快照顺序。
6. 候选沿用 `external_interaction`、`semantic_rank=3`、`sub_priority=12`、`safe_point`，进入既有候选池和 L2 仲裁。沿用已配置的 `owner_approach_response` intent 和 `approach_owner` Behavior。
7. Emotion 不增加事件映射。Action 不新增行为模板：现有 Action unit `ACT_INTERACT_APPROACH_OWNER_CLOSER` 提供安全停靠距离的主人靠近阶段。仓库虽登记通用 `wait_in_place` / `ACT_BASIC_WAIT`，其执行是固定 3 秒 hold，不等待主人互动信号，也没有和主人靠近组合的已登记流程；因此产品候选 `ACT_VISUAL_RECALL_APPROACH` 只作为文档别名，等待互动能力需明确披露为缺口。

## 兼容性

- 保持 `/perception/visual_event`、`std_msgs/msg/String`、`schema_version=1`、现有 RELIABLE 传输与 required 字段。
- 新增字段只使用现有可选 `event_instances` / `observation_status` / `source_observation_id`；按仓库事件命名规则登记 `EVT_VISION_OWNER_RECALL_GESTURE`。不把 `_gesture_diagnostics` 或 `recognized_actions[]` 加入 ROS 契约。
- 不修改主人身份、主人在场、弯腰/蹲下、Emotion、FALL 或 STOP 的事件生成/映射。
- 复用视觉目标 freshness 和 snapshot ordering 机制时，仅扩展新事件的资格集合；为既有事件补回归，证明行为不变。
- 先验证冻结视觉基线是否受影响。新增事件的专属纯契约样例可以增加，但不得自动重录或覆盖现有 baseline。

## 状态机约束

- 输入必须来自当前成功推理生成的新鲜 source observation；重复的 10 Hz JSON 快照幂等。
- ENTER 不额外计时，因为 GesturePose 已按现有动态动作稳定确认输出 `beckoning`/`waving`；召唤事件使用其稳定精确类别，不读取概率或 raw score。
- HOLD 只表示同一个识别周期的状态延续，不重新生成 TRIGGER。
- 只有有效的同主人当前源目标明确报告稳定 `beckoning` 与 `waving` 均解除才 EXIT；静态 `arms_raised` 不阻止释放。断流、推理错误、目标过期、Topic 中断与跨 epoch/track 的旧上下文不是负观测。
- 事件实例/目标上下文不跨 epoch 使用。目标/epoch 切换清除旧候选依据，并维持 disarmed，直至当前有效主人姿态确认解除。

## 验证与风险

- Vision 纯测试覆盖门控、ENTER/HOLD/EXIT、重复 source ID、漏手/几何无效/歧义腕点/连续性缺口、短缺失/无效观测、目标与 epoch 变换；真实 GesturePose 到事件状态机的逻辑回归不得把无效来源当作清除。节点序列测试验证 `events[]` 状态快照和实例 ID 加入/移除。
- Behavior 纯测试覆盖 whitelist、唯一新鲜 owner 绑定、实例去重、invalid/stale/context switch/epoch、派发前快照重验、候选优先级/仲裁元数据以及 Emotion 无路由。
- 应用视觉契约检查固定 v1 required baseline，验证新增事件作为可选 v1 事件在需要实例信息的消费者中正确传播。
- 跌倒/Stop 与现有主人/弯腰事件执行既有专门回归，防止新状态事件影响直接边沿去重。
- Action 的真实导航/机器人行为不在纯测试接受范围；本地没有硬件或真实生产 ROS 运行。即使软件链路通过，也只能声称主人靠近阶段已注册；通用固定时长 hold 不能证明“等待互动”已实现。

## 实施文件范围

- Vision: `modules/vision/marsdog_vision_interaction/core/`、事件类型/节点发布接线、配置/测试、`ROS2_CONTRACT.md` 和接口 manifest。
- Behavior: `visual_presence_contract.py`、`visual_event_consumer.py` / perception cache revalidation、候选映射配置及相应测试。
- Registry/contracts/docs: `interfaces/naming/catalog.json` 及必要的名称检查产物、`interfaces/application/visual-event-v1/README.md`、Behavior 事件对照/交接文档。
- 保持 Action 配置不变；只核对与文档引用已登记 unit。
