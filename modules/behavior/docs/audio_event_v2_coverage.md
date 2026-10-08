# AudioEvent v2 消费覆盖

本文记录行为树对 `/perception/audio_event` schema v2 的当前执行白名单。
Voice 的 `command_catalog.yaml` 是生产事件源；本文和
`config/event_intent_map.yaml` 只描述 Tree 已审核并能安全执行的子集。

## 执行条件

除硬件唤醒和 `EVT_STATE_CHANGED` 外，事件必须同时满足：

- `schema_version` 是整数 `2`；
- `event_type` 与消息字段一致，并存在于 Tree 精确映射中；
- `dispatch_role=specific_command`；
- `should_trigger_behavior_tree=true`；
- `command_id` 与映射中的 `expected_command_id` 一致；
- `specific_event_type` 与 `event_type` 一致。

`action`、`intent`、`control`、`action_name` 和 `behavior` 均不能选择 Tree
行为。旧 `EVT_VOICE_INTENT_COMMAND_*`、语义分类、诊断和 ASR `speech` 事件不会
生成候选，也不会结束语音等待阶段。`EVT_VOICE_CALL_NAME` 与
`EVT_VOICE_COMMAND_CALL_NAME` 是纯社交通知，同样不会创建唤醒会话或候选。

## 事件、行为与动作边界

目录事件是否“具体”不单独产生 `is_special` 标记。各层职责固定为：

```text
event_type -> command_id -> intent -> behavior_name -> Action stages -> ACT_*
```

- `event_type` 保留 Voice 发布的精确具体事件名；词库和 Model Intent 共享
  `EVT_VOICE_COMMAND_*`，不再维护第二套可执行别名；
- `command_id` 是跨项目稳定的具体指令身份；
- `behavior_name` 表示可仲裁、可验收的执行语义，不编码识别来源；
- `intent_source` 只记录 `command_lexicon / kws / rkllm` 等来源；
- 同一执行语义只有动作风格不同时使用 `variant`；
- 动作目标、目标约束、安全等级或完成条件不同时必须新增 Behavior。

Tree 将 `trigger_event`、`command_key`、`command_id`、
`command_catalog_version`、`intent_source`、`dispatch_role` 和
`specific_event_type` 传入 Action 的 `params_json`。Voice slots 中的
`action_name` 和自然语言 `behavior` 仅为上游参考，Tree 会过滤它们，禁止它们
直接选择 Action 单元。

## 当前已开放

Tree 当前有 28 个基础音频执行入口：硬件 `EVT_VOICE_WAKEUP`、22 个目录具体指令，
以及 WAIT、RETURN、BRING、FETCH、STOP 五个兼容入口。昵称社交事件不在执行入口中。
此外新增 52 个「直驱式短语」入口和 7 个「特殊事件」入口（见下），把原本走情绪
引擎或被忽略的社交/亲昵/情绪/饮食口语短语升级为 `EVT_VOICE_COMMAND_<ACTION>`
直驱确定性动作，或绑定到情绪行为。

另新增非核心词库指令 `PLAY_ALONE`（“自己去玩吧”）：
`EVT_VOICE_COMMAND_PLAY_ALONE` + `CMD_PLAY_ALONE` → `command_play_alone` →
`play_alone`，去随机位置自己玩。Lv1，长期 Goal（`timeout_sec=0`），冷却 0.2 秒。
Tree 与 Action 已对齐：Action 的 `uwb_roam` 阶段调用 `/go2/random_roam`，
成功到点并确认停稳后进入 `play` 阶段，随机执行一个姿态动作，然后在同一 Goal 内重复。
当前仅支持 Lite3 且 `uwb_follow_enabled=true`；实机联调仍需验证。

19 个核心产品指令与 Behavior 一一对应：

| 指令 | Behavior | 执行语义 |
|---|---|---|
| WALK | `walk_to_random_point` | 前往当前地图随机可导航点 |
| COME | `come_to_owner` | 移动到主人身边 |
| FOLLOW | `follow_owner` | 启动一个持续到取消的主人跟随 Goal |
| GO_OUT | `go_out_to_play` | 前往当前配置的玩耍区域；演示配置暂用随机区域 |
| GO_HOME | `go_home` | 前往 home 点；演示配置暂复用 A 点 |
| APPROACH | `approach_owner` | 短距离靠近主人，不复用唤醒者会话编排 |
| BACK_UP | `back_up` | 从当前位置后退并停车 |
| SIT | `sit_down` | 切换为坐姿 |
| LIE_DOWN | `lie_down` | 切换为趴卧姿态 |
| PLAY_DEAD | `play_dead` | 装死动作 |
| STAND_UP | `stand_up` | 切换为站姿，完成后结束 |
| STAND_STILL | `stand_still` | 确保站姿后保持不动 |
| SHAKE_HAND | `give_paw` | 握手 |
| HIGH_FIVE | `high_five` | 击掌 |
| SPIN | `spin_around` | 原地转圈 |
| ROLL_OVER | `roll_over` | 翻滚 |
| HOLD_POSITION | `hold_position` | 保持当前姿态和位置，不是急停 |
| DROP | `drop_object` | 松开口中物体 |
| QUIET | `quiet` | 停止当前发声，不改变姿态和底盘状态 |

Model Intent 与确定性词库均发布上表同一个 `EVT_VOICE_COMMAND_<ACTION>`，Tree
只保留这一套精确映射。`EVT_VOICE_INTENT_COMMAND_<ACTION>` 不作为兼容入口。

三个目录命令先经过内部需求门控，再沿用现有需求 Behavior：

| 事件 | 内部条件（严格 `>`） | 复用 Behavior |
|---|---:|---|
| `EVT_VOICE_COMMAND_TOILET` | `Bladder > 50` | `barkShortAlert` |
| `EVT_VOICE_COMMAND_CLEAN` | `Cleanliness > 40` | `lickPaws` |
| `EVT_VOICE_COMMAND_SLEEP` | `Sleepiness > 50` | `sleepOnSide` |

门控在候选入池、语音会话释放和去重记录之前执行。内部状态未初始化、配置格式
错误、数值非有限、等于阈值或低于阈值时均失败关闭；通过后把观测值写入候选参数，
供日志和 Action Goal 审计。它们不新建 Behavior，也不改变既有需求 signal 路由。

FETCH 会把规范物体名和匹配证据保留在 Action Goal 参数中。Voice 不提供正式视觉
目标 ID；当前 Action 仍使用通用 `ACT_OBJECT_FETCH`，因此“按指定视觉目标抓取”的
硬件闭环需要 Tree/Vision/Action 另行联合验收。

### 直驱式短语（direct-drive phrases）

52 个社交/亲昵/情绪/饮食口语短语直驱确定性动作，按 10 组映射到 Lv1 语义
Behavior（`event_type`/`command_id` 采用 Voice 词库权威命名）：

| 组 | 短语 → Behavior |
|---|---|
| 亲昵安抚 | 不怕不怕 → `comfort_soothe`，没事没事 → `comfort_reassure`，疼不疼 → `care_inquire`，摸摸头 → `pet_head`，抱抱 → `hug` |
| 拒绝否定 | 我不要 → `refuse`，我不玩 → `refuse_play` |
| 找人 | 去找爸爸 → `find_dad`，去找妈妈 → `find_mom` |
| 表演 | 跳个舞 → `dance` |
| 取物 | 拿给我 → `bring_to_me`，给我 → `give_me`，去拿 → `go_fetch`，叼回来 → `bring_back`，捡球 → `fetch_ball`，找玩具 → `find_toy` |
| 留守/等待 | 你自己在家 → `stay_home`，等我回来 → `wait_return` |
| 出行/归来 | 我要出门了 → `farewell_leave`，拜拜 → `farewell_bye`，再见 → `farewell_goodbye`，我回来了 → `greet_return` |
| 询问回应 | 你在干嘛 → `report_activity`，你在哪里 → `report_location`，你怎么了 → `report_state`，你想什么 → `respond_thought`，舒服吗 → `respond_comfort`，喜欢吗 → `respond_like`，好玩吗 → `respond_fun`，你听得懂吗 → `respond_understand`，你会什么 → `show_skill`，你学会了吗 → `respond_learned` |
| 负面情绪 | 我好想你 → `miss_owner`，我累了 → `tired`，我有点烦 → `annoyed`，今天不开心 → `unhappy`，过得不太顺利 → `downcast`，我要抑郁了 → `depressed`，压力好大 → `stressed`，我好孤独 → `lonely`，我头疼 → `unwell` |
| 正面情绪 | 心情美美的 → `cheerful`，很开心 → `happy`，状态特别好 → `great_form`，特别棒 → `great`，浑身轻松 → `relaxed`，好日子 → `wonderful_day`，太幸运 → `lucky` |
| 饮食直驱 | 吃饭 → `eat_meal`，吃零食 → `eat_snack`，吃罐罐 → `eat_canned_food`，你想吃什么 → `respond_food_preference` |

这些短语与情绪引擎（`EMO_*_TRIGGERED` → `express*`）并存且互不替代：短语走
`audio_direct` 白名单直驱确定性动作，情绪引擎仍按阈值触发随机情绪行为。所有
Behavior 均 `action_sequence: []`，物理动作归 `marsdog_action_executor`。

### 词库社交反应（`audio_reaction`）与有界特殊事件

| 事件 | 处理 |
|---|---|
| `EVT_VOICE_COMMAND_PRAISE` | Lv1 一次性愉悦/兴奋反应；会话内使用原地行为 |
| `EVT_VOICE_COMMAND_SCOLD` | Lv1 一次性焦虑/好奇/恐惧反应；会话内使用原地行为 |
| `EVT_VOICE_COMMAND_PLAY` | 绑定兴奋（`expressExcitement`） |
| `EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY` | 按饥饿分流：`Hunger > 70` → `respond_hungry_yes`，否则 `respond_hungry_no`（阈值待确认） |
| `EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY` | 按饥饿分流：`Hunger > 70` → `respond_want_eat_yes`，否则 `respond_want_eat_no`（阈值待确认） |
| `EVT_VOICE_COMMAND_RESPOND_EATING_QUERY` | 进食中则打断 → `look_at_owner_brief` → 完成后恢复进食；否则直接 `look_at_owner_brief` |

`EVT_VOICE_COMMAND_CALL_NAME` 不在上述可执行路由中，仍是纯社交通知。

## 待开放

19 个核心产品指令以及 TOILET、CLEAN、SLEEP 已加入 Tree；后三个按上表复用
现有生理需求 Behavior。其余目录事件仍需逐项确定专用语义和 Action 能力后开放。

新增映射仍禁止使用近似替代：

- `HOLD_POSITION` 不能映射为 Lv0 STOP，也不能映射为会坐下的 `wait_in_place`；
- `QUIET` 只停止叫声，不是急停；
- `BACK_UP`、兼容 `RETURN/CMD_BACK` 和 `COME/CMD_COME_HERE` 是三条不同动作；
- `APPROACH` 不能直接复用带唤醒会话编排的 `approach_voice_caller`。

Voice 确定性目录目前有 81 个路由组。Tree 尚未映射的产品事件继续记录为
`unmapped`，不会根据前缀、`action_name` 或粗粒度意图自动生成行为。每增加一个
产品事件，都必须同步本表、精确映射、Behavior、Action 模板和端到端测试。

按 Voice `2026-09-12-social-reaction-v5` 交叉检查，81 个目录路由中 CALL_NAME、
PRAISE、SCOLD 三个为非执行社交事件，其余 78 个可执行。其中 PRAISE/
SCOLD 通过独立 `social_reaction` 权限进入 Tree，CALL_NAME 仍不进入。Tree 与
目录精确重合 22 个可执行事件，尚有 56 个目录执行事件未开放。Tree 另外保留
WAIT、RETURN、BRING、FETCH、STOP 五个兼容入口；硬件 WAKEUP 也不属于词库目录，
均不能计入目录覆盖率。

Voice 目录里的 `action_name=ACT_*` 是参考动作名，Action 使用自身正式单元。本批
新行为已建立独立的 `ACT_NAV_* / ACT_BASIC_* / ACT_CONTROL_* / ACT_INTERACT_*`
映射；仍不能把 Voice 的 `action_name` 直接塞入
`/execute_behavior.behavior_name`。

`walk_to_random_point`、`go_out_to_play` 和 `go_home` 依赖 Action Nav2 配置，控制器
不可用时失败关闭。演示配置中 GO_OUT 与 WALK 共用随机可导航区域，GO_HOME 暂复用
A 点；部署现场必须替换为实际 play/home 区域或点位。`approach_owner` 和另外两个
主人接近行为当前收到的 Vision 结果只有视觉候选，没有地图几何；Action 因此失败关闭，
不发送 Nav2 目标。要恢复导航接近，需由后续兼容工作提供经过验证的导航几何来源。

## 验收边界

源码测试需要覆盖接收、拒绝原因、候选生成、会话释放、去重和 Goal 参数。部署后还要
检查实际安装配置、ROS Topic 消息、Action feedback/result；源码测试通过不等于视觉、
底盘和机械动作已经完成硬件验收。
