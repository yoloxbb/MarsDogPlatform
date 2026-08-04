# 事件-行为对照表

按当前 YAML 配置整理，反映当前系统实际映射。

---

## 情绪 V2 事件 → 行为（全部 Lv.5，result_mapping=null）

| 事件 | 阈值 | 检测到人时的 Behavior | 无人时的 Behavior | Variant |
|------|:----:|----------------------|------------------|---------|
| EMO_CALM_TRIGGERED | `>= 0` | `expressCalmWithHuman` | `expressCalmAlone` | calm |
| EMO_JOY_TRIGGERED | `>= 30` | `expressJoyWithHuman` | `expressJoyAlone` | joy |
| EMO_EXCITE_TRIGGERED | `>= 40` | `expressExcitementWithHuman` | `expressExcitementAlone` | excitement |
| EMO_ANXIETY_TRIGGERED | `>= 25` | `expressAnxietyWithHuman` | `expressAnxietyAlone` | anxiety |
| EMO_FEAR_TRIGGERED | `>= 30` | `expressFearWithHuman` | `expressFearAlone` | fear |
| EMO_CURIOUS_TRIGGERED | `>= 20` | `expressCuriosityWithHuman` | `expressCuriosityAlone` | curiosity |

每个情绪 signal_event 都先异步调用 `/perception/vision/task` 的
`check_person`：

- 有人：生成独立的 `*WithHuman` Behavior，携带人物 target 和
  `interaction_mode=interactive`。
- 无人：生成独立的 `*Alone` Behavior，设置
  `interaction_mode=solo`。
- 服务不可用时使用 `/perception/visual_event` 人物缓存；Standalone 使用
  虚拟人物场景。
- 等待 Service 期间如果情绪已恢复，迟到结果会被丢弃，不创建候选。

动作执行器目前仍使用六个基础 `express*` 动作模板。因此发送 Action Goal
时通过 `executor_behavior_name` 映射回基础模板，并使用 interactive/solo ACT
池；行为树候选、当前行为和结果反馈始终保留上述 12 个独立 Behavior 名称。

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
  `inspectKnownObject + object_category` 选择已有动作模板。
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

- 当前 ROS2 运行时拦截 `EVT_VOICE_CALL_NAME`，只开启会话级
  `face_body_centering`，不创建动作候选；`respond_owner_call` 映射仅保留给
  standalone/兼容测试。
- 姿态、移动和交互类强指令一条指令对应一个专用 Behavior。
- `EVT_VOICE_COMMAND_DROP` 是 Lv.1 的 `drop_object`；
  `EVT_VOICE_COMMAND_STOP` 进入 Lv.0 `emergency_stop`。
- 行为决策只读取完整 `event_type`，不接受额外指令 ID 的旧封装。

### `event_type` 映射

| 事件 | Behavior | Lv | sub_priority |
|------|----------|:--:|:--:|
| EVT_VOICE_CALL_NAME | —（开启 `face_body_centering`） | — | — |
| EVT_VOICE_COMMAND_SIT | `sit_down` | 1 | 1 |
| EVT_VOICE_COMMAND_LIE_DOWN | `lie_down` | 1 | 1 |
| EVT_VOICE_COMMAND_STAND_UP | `stand_up` | 1 | 1 |
| EVT_VOICE_COMMAND_WAIT | `wait_in_place` | 1 | 1 |
| EVT_VOICE_COMMAND_COME | `come_to_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_FOLLOW | `follow_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_SHAKE_HAND | `give_paw` | 1 | 1 |
| EVT_VOICE_COMMAND_HIGH_FIVE | `high_five` | 1 | 1 |
| EVT_VOICE_COMMAND_ROLL_OVER | `roll_over` | 1 | 1 |
| EVT_VOICE_COMMAND_SPIN | `spin_around` | 1 | 1 |
| EVT_VOICE_COMMAND_RETURN | `return_to_owner` | 1 | 1 |
| EVT_VOICE_COMMAND_DROP | `drop_object` | 1 | 1 |
| EVT_VOICE_COMMAND_PLAY_DEAD | `play_dead` | 1 | 1 |
| EVT_VOICE_COMMAND_BRING | `bring_object` | 1 | 1 |
| EVT_VOICE_COMMAND_FETCH | `fetch_object` | 1 | 1 |
| EVT_VOICE_COMMAND_STOP | `emergency_stop` | 0 | 1 |

---

> 映射来源：`config/event_intent_map.yaml`、`config/emotion_behavior_map.yaml`、
> `config/intent_action_pool.yaml`。
