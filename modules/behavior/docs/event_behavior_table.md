# 事件-行为对照表

按当前 YAML 配置整理，反映当前系统实际映射。

---

## 视觉直接事件 → 行为（Lv1）

| `/perception/visual_event.events[]` | Behavior | priority_level | sub_priority | TTL |
|---|---|:---:|:---:|:---:|
| `EVT_VISION_FALL` | `respond_person_fall` | 1 | 12 | 8s |
| `EVT_VISION_STOP_GESTURE` | `respond_stop_gesture` | 1 | 12 | 8s |

`Lv1.2` 是本项目的表述约定，实际 Action Goal 仍只有整数
`priority_level=1`；`.2` 通过候选内部 `sub_priority=12` 表示“视觉”。
这些 Behavior 会保留 `trigger_event`、`visual_header`、`active_target` 和
`hands` 到 `params_json`。FALL/STOP 以原样、区分大小写的 `behavior_name` 发送给
`/execute_behavior`。

`/perception/visual_event` 是 10 Hz 状态快照，不是一次性边沿总线。连续包中的
同名事件只在首次出现时触发；先消失后再出现时才重新触发。候选池还会
对 queued/in-flight 的同名 Behavior 做二次去重。

> 跨项目约束：动作项目的 `config/behavior_tree_actions.yaml` 必须注册
> `respond_person_fall` 和 `respond_stop_gesture`。

---

## 情绪 V2 事件 → 行为（全部 Lv.5，result_mapping=null）

| 事件 | 阈值 | 检测到人时 | 语音 WAITING 原地分支 | 无人时 | Variant |
|------|:----:|------------|----------------------|--------|---------|
| EMO_CALM_TRIGGERED | `>= 0` | `expressCalmWithHuman` | `expressCalmInPlaceWithHuman` | `expressCalmAlone` | calm |
| EMO_JOY_TRIGGERED | `>= 30` | `expressJoyWithHuman` | `expressJoyInPlaceWithHuman` | `expressJoyAlone` | joy |
| EMO_EXCITE_TRIGGERED | `>= 40` | `expressExcitementWithHuman` | `expressExcitementInPlaceWithHuman` | `expressExcitementAlone` | excitement |
| EMO_ANXIETY_TRIGGERED | `>= 25` | `expressAnxietyWithHuman` | `expressAnxietyInPlaceWithHuman` | `expressAnxietyAlone` | anxiety |
| EMO_FEAR_TRIGGERED | `>= 30` | `expressFearWithHuman` | `expressFearInPlaceWithHuman` | `expressFearAlone` | fear |
| EMO_CURIOUS_TRIGGERED | `>= 20` | `expressCuriosityWithHuman` | `expressCuriosityInPlaceWithHuman` | `expressCuriosityAlone` | curiosity |

每个情绪 signal_event 都先异步调用 `/perception/vision/task` 的
`check_person`：

- 有人：生成独立的 `*WithHuman` Behavior，携带人物 target 和
  `interaction_mode=interactive`。
- 无人：生成独立的 `*Alone` Behavior，设置
  `interaction_mode=solo`。
- 语音会话处于 `WAITING`，或语音指令已得到真实终态，且功能开关已启用：
  重新确认人物目标后选择 `*InPlaceWithHuman`。保留 `interaction_id` 用于
  关联，设置 `mobility_policy=in_place` 和 `lifecycle_scope=behavior`；表达
  动作与对应普通 `*WithHuman` 相同，不含 `target_approach`，仍可能包含
  Go2/Lite3 底盘动作；Action 前台执行锁与后台 attention 控制串行。
- 转向、靠近、后台跟随或高等级行为占用执行资源时，先保留情绪意图。状态
  恢复后撤销；语音 idle 后仍有效则重新选择视觉分支。
- 服务不可用时使用 `/perception/visual_event` 人物缓存；Standalone 使用
  虚拟人物场景。
- 等待 Service 期间如果情绪已恢复，迟到结果会被丢弃，不创建候选。

动作执行器目前仍使用六个基础 `express*` 动作模板。因此发送 Action Goal
时通过 `executor_behavior_name` 映射回基础模板，并使用 interactive/solo ACT
池；行为树候选、当前行为和结果反馈始终保留上述独立 Behavior 名称。启用语音
等待原地分支后，六类情绪共有 18 个上下文 Behavior。

情绪 V2 只有阈值上升沿事件，没有 LOW/MID/HIGH/NORMAL 或恢复事件。
`/emotion/state.emotions.<name>.triggered` 是当前状态和恢复判断的唯一依据；
state 本身不会生成行为候选。Calm 虽然始终为 triggered，但正常启动不会产生
signal_event，因此不会因状态心跳反复触发 `expressCalm`。

非平静情绪在上升沿启动一次“持续表达会话”。每个动作完成后，若对应
`triggered` 仍为 `true`，行为树间隔 0.8 秒重新解析人物上下文并续排同类行为；
多个情绪同时等待时采用 `Fear > Anxiety > Excite > Joy > Curious`。默认最多
执行 4 次且总时长不超过 15 秒。恢复、动作失败或达到任一上限都会终止续排，
更高等级的内部需求、外部指令和安全行为仍按原优先级规则抢占。

配置中的 `level=LOW` 仅用于选择动作执行器现有的情绪动作池，不是重新引入
V1 的 LOW 事件或状态等级。

## 内部需求 V2 事件 → 行为

| 事件 | 视觉条件 | Behavior | Lv | sub_priority | Variant | result_mapping |
|------|----------|----------|:--:|:------------:|---------|----------------|
| NEED_HUNGER_TRIGGERED | 识别到狗粮 | `eatNormally` | 3 | 0 | food_visible | ACTION_EAT |
| NEED_HUNGER_TRIGGERED | 未识别到狗粮 | `seekFood` | 3 | 0 | food_search | ACTION_FOOD_SEEK |
| NEED_HUNGER_OVERFLOW | 识别到狗粮 | `eatExcitedly` | 3 | 0 | food_visible_urgent | ACTION_EAT |
| NEED_HUNGER_OVERFLOW | 未识别到狗粮 | `seekFoodUrgently` | 3 | 0 | food_search_urgent | ACTION_FOOD_SEEK |
| NEED_BLADDER_TRIGGERED | — | `barkShortAlert` | 2 | 0 | request | ACTION_DEFECATE |
| NEED_SLEEPINESS_TRIGGERED | — | `sleepOnSide` | 2 | 0 | light | ACTION_SLEEP |
| NEED_SLEEPINESS_OVERFLOW | — | `sleepNow` | 2 | 0 | deep | ACTION_SLEEP |
| NEED_CLEANLINESS_TRIGGERED | — | `lickPaws` | 3 | 0 | light | ACTION_GROOM |
| NEED_ENERGY_TRIGGERED | — | `restInPlace` | 0 | 0 | low_energy | ACTION_RECHARGE |
| NEED_ENERGY_OVERFLOW | — | `recharge` | 0 | 0 | critical | ACTION_RECHARGE |
| NEED_SOCIAL_TRIGGERED | 有人 | `seekHumanInteraction` | 4 | 2 | human_seek | ACTION_ATTENTION_SEEK |
| NEED_SOCIAL_TRIGGERED | 无人、有猫/狗 | `testAnimalBoundary` | 4 | 2 | animal_boundary | ACTION_BOUNDARY_TEST |
| NEED_SOCIAL_URGENT | 有人 | `seekInteraction` | 4 | 1 | human_engage | ACTION_ATTENTION_SEEK |
| NEED_SOCIAL_URGENT | 无人、有猫/狗 | `greetAnimal` | 4 | 1 | animal_greet | ACTION_SOCIAL_GREET |
| NEED_SOCIAL_OVERFLOW | 有人 | `inviteHumanToPlay` | 4 | 0 | human_play | ACTION_PLAY_INVITE |
| NEED_SOCIAL_OVERFLOW | 无人、有猫/狗 | `inviteAnimalToPlay` | 4 | 0 | animal_play | ACTION_PLAY_INVITE |
| NEED_EXPLORATION_TRIGGERED | 拖鞋/袜子/玩具 | `inspectFamiliarPlayItem` | 4 | 0 | play_item | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 垃圾桶 | `inspectTrashCan` | 4 | 0 | trash_can | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 快递盒子 | `inspectDeliveryBox` | 4 | 0 | delivery_box | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 纸巾 | `inspectTissuePaper` | 4 | 0 | tissue | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 门 | `inspectDoor` | 4 | 0 | door | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 狗粮/狗食容器 | `inspectDogFood` | 4 | 0 | dog_food | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 只有陌生物品 | `inspectObject` | 4 | 0 | unfamiliar | ACTION_OBJECT_EXPLORE |
| NEED_EXPLORATION_TRIGGERED | 未检测到物品 | `exploreRoom` | 4 | 0 | room | ACTION_SPACE_EXPLORE |

Hunger、Social 和 Exploration 会先调用视觉服务 `/perception/vision/task`：

- Hunger 执行 `detect_objects`。`dog food can / dog treat bag` 等狗粮标签
  进入进食路由；未识别到狗粮时进入找食物路由。
- Social 先执行 `check_person`，有人时不再选择动物；无人时执行
  `detect_objects`，只接受 `cat / dog`。无人且无猫狗时不创建候选。
- Exploration 执行 `detect_objects`。熟悉物品按上述 6 类选择专用 Behavior；
  其余物品归为陌生物品；空结果执行空间探索。
- 6 个探索 Behavior 对下游保留独立名字，当前动作执行器兼容层使用
  六个熟悉物体路由保留各自的具体 Behavior 名称，并通过
  `object_category` 选择对应动作模板；不再覆盖为未注册的
  `inspectKnownObject`。
- 未安装视觉 Service 类型或服务暂不可用时，使用最新
  `/perception/visual_event` 缓存；Standalone 使用虚拟视觉模块。

需求消息只接受 `schema_version="2.0"`。首次触发线读取
`triggerThreshold / triggerOperator`；可选中间紧急线读取
`urgentThreshold / urgentOperator`。所有比较均为严格 `gt`。

| 需求 | TRIGGERED | URGENT | OVERFLOW |
|------|-----------|--------|----------|
| Hunger | `>70` | — | `>90` |
| Bladder | `>75` | — | — |
| Sleepiness | `>65` | — | `>90` |
| Cleanliness | `>70` | — | — |
| Energy | `>80` | — | `>90` |
| Social | `>60` | `>70` | `>85` |
| Exploration | `>60` | — | — |

Bladder、Cleanliness、Exploration 到 100 仍为 `TRIGGERED`，不会产生
`OVERFLOW`。Energy 表示电量缺口（`100 - 当前电量百分比`），但行为结果
metadata 的 `energyValue / energy_value / batteryValue` 仍表示实际电量。

## 语音事件 → 行为

设计约束：

- `EVT_VOICE_WAKEUP` 生成 `respond_owner_call` 原地转向；匹配同一 `wake_id`
  的声纹结果为主人或家人且能绑定人体时，内部生成 `approach_voice_caller`。
  陌生人、未判定和声纹超时均原地等待。
- `EVT_VOICE_CALL_NAME` 与 `EVT_VOICE_COMMAND_CALL_NAME` 只是昵称社交通知，
  不创建语音会话，也不生成候选。
- 姿态、移动和交互类强指令一条指令对应一个专用 Behavior。
- `EVT_VOICE_COMMAND_DROP` 是 Lv.1 的 `drop_object`；
  `EVT_VOICE_COMMAND_STOP` 进入 Lv.0 `emergency_stop`。
- 行为选择仍只由完整 `event_type` 决定；`command_id` 只用于验证该事件
  是否与上游契约一致，不会反向选择 Behavior。
- 具体指令必须是 AudioEvent schema v2，且
  `dispatch_role=specific_command`、`should_trigger_behavior_tree=true`、
  `specific_event_type=event_type`。

### `event_type` 映射

| 事件 | Behavior | Lv | sub_priority |
|------|----------|:--:|:--:|
| EVT_VOICE_WAKEUP | `respond_owner_call` | 1 | 1 |
| 内部：已识别主人/家人且人体目标有效 | `approach_voice_caller` | 1 | 2 |
| EVT_VOICE_COMMAND_WALK | `walk_to_random_point` | 1 | 1 |
| EVT_VOICE_COMMAND_PLAY_ALONE | `play_alone` | 1 | 1 |
| EVT_VOICE_COMMAND_GO_OUT | `go_out_to_play` | 1 | 1 |
| EVT_VOICE_COMMAND_GO_HOME | `go_home` | 1 | 1 |
| EVT_VOICE_COMMAND_APPROACH | `approach_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_BACK_UP | `back_up` | 1 | 1 |
| EVT_VOICE_COMMAND_SIT | `sit_down` | 1 | 1 |
| EVT_VOICE_COMMAND_LIE_DOWN | `lie_down` | 1 | 1 |
| EVT_VOICE_COMMAND_STAND_UP | `stand_up` | 1 | 1 |
| EVT_VOICE_COMMAND_STAND_STILL | `stand_still` | 1 | 1 |
| EVT_VOICE_COMMAND_HOLD_POSITION | `hold_position` | 1 | 1 |
| EVT_VOICE_COMMAND_WAIT | `wait_in_place` | 1 | 1 |
| EVT_VOICE_COMMAND_COME | `come_to_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_FOLLOW | `follow_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_SHAKE_HAND | `give_paw` | 1 | 1 |
| EVT_VOICE_COMMAND_HIGH_FIVE | `high_five` | 1 | 1 |
| EVT_VOICE_COMMAND_ROLL_OVER | `roll_over` | 1 | 1 |
| EVT_VOICE_COMMAND_SPIN | `spin_around` | 1 | 1 |
| EVT_VOICE_COMMAND_RETURN | `return_to_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_DROP | `drop_object` | 1 | 1 |
| EVT_VOICE_COMMAND_QUIET | `quiet` | 1 | 1 |
| EVT_VOICE_COMMAND_PLAY_DEAD | `play_dead` | 1 | 1 |
| EVT_VOICE_COMMAND_BRING | `bring_object` | 1 | 1 |
| EVT_VOICE_COMMAND_FETCH | `fetch_object` | 1 | 1 |
| EVT_VOICE_COMMAND_TOILET | `Bladder > 50` 时 `barkShortAlert` | 1 | 1 |
| EVT_VOICE_COMMAND_CLEAN | `Cleanliness > 40` 时 `lickPaws` | 1 | 1 |
| EVT_VOICE_COMMAND_SLEEP | `Sleepiness > 50` 时 `sleepOnSide` | 1 | 1 |
| EVT_VOICE_COMMAND_STOP | `emergency_stop` | 0 | 1 |

### 直驱式短语 → 行为（Lv1，sub_priority=1）

这些社交/亲昵/情绪口语短语原本走情绪引擎或被忽略，现升级为
`EVT_VOICE_COMMAND_<ACTION>` 命令事件，直驱确定性动作
（`source=audio_direct`，走候选池 + 仲裁）。`event_type`/`command_id` 采用
Voice 词库权威命名；`behavior_name` 为描述性短名，动作语义待与 Action 侧对齐，
物理动作归 `marsdog_action_executor`（`action_sequence: []`）。

| 组 | Behavior（对应短语） |
|---|---|
| 亲昵安抚 | `comfort_soothe`（不怕不怕）、`comfort_reassure`（没事没事）、`care_inquire`（疼不疼）、`pet_head`（摸摸头）、`hug`（抱抱） |
| 拒绝否定 | `refuse`（我不要）、`refuse_play`（我不玩） |
| 找人 | `find_dad`（去找爸爸）、`find_mom`（去找妈妈） |
| 表演 | `dance`（跳个舞） |
| 取物 | `bring_to_me`（拿给我）、`give_me`（给我）、`go_fetch`（去拿）、`bring_back`（叼回来）、`fetch_ball`（捡球）、`find_toy`（找玩具） |
| 留守/等待 | `stay_home`（你自己在家）、`wait_return`（等我回来） |
| 出行/归来 | `farewell_leave`（我要出门了）、`farewell_bye`（拜拜）、`farewell_goodbye`（再见）、`greet_return`（我回来了） |
| 询问回应 | `report_activity`（你在干嘛）、`report_location`（你在哪里）、`report_state`（你怎么了）、`respond_thought`（你想什么）、`respond_comfort`（舒服吗）、`respond_like`（喜欢吗）、`respond_fun`（好玩吗）、`respond_understand`（你听得懂吗）、`show_skill`（你会什么）、`respond_learned`（你学会了吗） |
| 负面情绪 | `miss_owner`（我好想你）、`tired`（我累了）、`annoyed`（我有点烦）、`unhappy`（今天不开心）、`downcast`（过得不太顺利）、`depressed`（我要抑郁了）、`stressed`（压力好大）、`lonely`（我好孤独）、`unwell`（我头疼） |
| 正面情绪 | `cheerful`（心情美美的）、`happy`（很开心）、`great_form`（状态特别好）、`great`（特别棒）、`relaxed`（浑身轻松）、`wonderful_day`（好日子）、`lucky`（太幸运） |
| 饮食直驱 | `eat_meal`（吃饭）、`eat_snack`（吃零食）、`eat_canned_food`（吃罐罐）、`respond_food_preference`（你想吃什么） |

`unhappy`、`miss_owner`、`farewell_leave` 在候选入队前由 Tree 调用
`query_targets`，仅将带稳定
`vision_epoch + target_id`、`identity=owner`、`identity_state=confirmed_known`
且仍在跟踪的目标写入 `params_json.target`；找不到主人时不下发移动 Goal，
后续新语音会作废迟到的视觉结果。

`approach_owner`、`come_to_owner`、`return_to_owner` 不做 Tree 侧
`query_targets`，直接下发 Goal。Action 在执行时从新鲜的
`/perception/visual_event.active_target` 绑定人体 `target_id`，允许视觉身份
`unknown`，设置严格目标锁和 1.5 m 停靠距离；然后执行一次
`locate_person_once`，按响应需要发送一次 Nav2 导航 Goal。没有新鲜人体轨迹
时有限等待后失败并停车。语音 idle 不取消已接管的有界导航 Goal。此时目标是
视觉当前人体，不能仅凭该结果证明是说话者或主人。具体 Go2/Lite3 底盘由
Action 的运行参数选择。

### 词库社交反应（`audio_reaction`）与有界特殊事件

| 事件 | 处理 |
|---|---|
| `EVT_VOICE_COMMAND_PRAISE` | `audio_reaction` Lv1 一次性愉悦/兴奋；会话内原地表达 |
| `EVT_VOICE_COMMAND_SCOLD` | `audio_reaction` Lv1 一次性焦虑/好奇/恐惧；会话内原地表达 |
| `EVT_VOICE_COMMAND_PLAY` | 绑定兴奋（`expressExcitement`） |
| `EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY` | 按饥饿分流：`Hunger > 70` → `respond_hungry_yes`，否则 `respond_hungry_no`（阈值待确认） |
| `EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY` | 按饥饿分流：`Hunger > 70` → `respond_want_eat_yes`，否则 `respond_want_eat_no`（阈值待确认） |
| `EVT_VOICE_COMMAND_RESPOND_EATING_QUERY` | 进食中则打断 → `look_at_owner_brief` → 完成后恢复进食；否则直接 `look_at_owner_brief` |

`EVT_VOICE_COMMAND_CALL_NAME` 仅保留昵称社交语义，不创建 Tree 候选。

词库和 Model Intent 的执行事件统一使用表中的 `EVT_VOICE_COMMAND_<ACTION>`；
旧 `EVT_VOICE_INTENT_COMMAND_<ACTION>` 不再开放。FETCH 额外要求非 `NONE` 且
位于白名单中的 `object_name` 槽位。三个需求命令在候选入池及语音会话副作用之前
读取内部需求的最新值，状态缺失、等于阈值或低于阈值均失败关闭。完整清单见
[AudioEvent v2 消费覆盖](audio_event_v2_coverage.md)。

---

> 映射来源：`config/event_intent_map.yaml`、`config/emotion_behavior_map.yaml`、
> `config/intent_action_pool.yaml`。
