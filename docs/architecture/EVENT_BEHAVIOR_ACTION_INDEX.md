# MarsDog 事件行为动作配置索引

配套说明：[运行架构与扩展指南](EVENT_BEHAVIOR_ACTION.md)。
本索引按 2026-09-30 的代码基线 `926f14b` 读取配置生成。它描述配置可达关系，不代表每个动作已在所选设备实现或通过实机验证。
事件前置授权、会话、目标、需求阈值和仲裁仍需通过；节点内的特殊交互分支以主说明和源代码为准。

## 1 事件到行为

同一 intent 配置多个候选时，IntentMapper 当前随机选择一个行为；下表列出配置选项。

| 来源 | 事件 | 上下文路由 | Lv | intent | BT 行为 | Action 下游名 |
| --- | --- | --- | ---: | --- | --- | --- |
| `audio_direct` | `EVT_VOICE_WAKEUP` | — | 1 | `orient_to_sound` | `respond_owner_call` | `respond_owner_call` |
| `audio_direct` | `EVT_VOICE_COMMAND_WALK` | — | 1 | `command_walk` | `walk_to_random_point` | `walk_to_random_point` |
| `audio_direct` | `EVT_VOICE_COMMAND_PLAY_ALONE` | — | 1 | `command_play_alone` | `play_alone` | `play_alone` |
| `audio_direct` | `EVT_VOICE_COMMAND_GO_OUT` | — | 1 | `command_go_out` | `go_out_to_play` | `go_out_to_play` |
| `audio_direct` | `EVT_VOICE_COMMAND_GO_HOME` | — | 1 | `command_go_home` | `go_home` | `go_home` |
| `audio_direct` | `EVT_VOICE_COMMAND_APPROACH` | — | 1 | `command_approach` | `approach_owner` | `approach_owner` |
| `audio_direct` | `EVT_VOICE_COMMAND_BACK_UP` | — | 1 | `command_back_up` | `back_up` | `back_up` |
| `audio_direct` | `EVT_VOICE_COMMAND_SIT` | — | 1 | `command_sit` | `sit_down` | `sit_down` |
| `audio_direct` | `EVT_VOICE_COMMAND_LIE_DOWN` | — | 1 | `command_lie_down` | `lie_down` | `lie_down` |
| `audio_direct` | `EVT_VOICE_COMMAND_STAND_UP` | — | 1 | `command_stand_up` | `stand_up` | `stand_up` |
| `audio_direct` | `EVT_VOICE_COMMAND_STAND_STILL` | — | 1 | `command_stand_still` | `stand_still` | `stand_still` |
| `audio_direct` | `EVT_VOICE_COMMAND_HOLD_POSITION` | — | 1 | `command_hold_position` | `hold_position` | `hold_position` |
| `audio_direct` | `EVT_VOICE_COMMAND_WAIT` | — | 1 | `command_wait` | `wait_in_place` | `wait_in_place` |
| `audio_direct` | `EVT_VOICE_COMMAND_COME` | — | 1 | `command_come_here` | `come_to_owner` | `come_to_owner` |
| `audio_direct` | `EVT_VOICE_COMMAND_SHAKE_HAND` | — | 1 | `command_handshake` | `give_paw` | `give_paw` |
| `audio_direct` | `EVT_VOICE_COMMAND_HIGH_FIVE` | — | 1 | `command_high_five` | `high_five` | `high_five` |
| `audio_direct` | `EVT_VOICE_COMMAND_FOLLOW` | — | 1 | `command_follow` | `follow_owner` | `follow_owner` |
| `audio_direct` | `EVT_VOICE_COMMAND_ROLL_OVER` | — | 1 | `command_roll` | `roll_over` | `roll_over` |
| `audio_direct` | `EVT_VOICE_COMMAND_SPIN` | — | 1 | `command_spin` | `spin_around` | `spin_around` |
| `audio_direct` | `EVT_VOICE_COMMAND_RETURN` | — | 1 | `command_retrieve` | `return_to_owner` | `return_to_owner` |
| `audio_direct` | `EVT_VOICE_COMMAND_DROP` | — | 1 | `command_spit_out` | `drop_object` | `drop_object` |
| `audio_direct` | `EVT_VOICE_COMMAND_QUIET` | — | 1 | `command_quiet` | `quiet` | `quiet` |
| `audio_direct` | `EVT_VOICE_COMMAND_TOILET` | — | 1 | `command_toilet` | `barkShortAlert` | `barkShortAlert` |
| `audio_direct` | `EVT_VOICE_COMMAND_CLEAN` | — | 1 | `command_clean` | `lickPaws` | `lickPaws` |
| `audio_direct` | `EVT_VOICE_COMMAND_SLEEP` | — | 1 | `command_sleep` | `sleepOnSide` | `sleepOnSide` |
| `audio_direct` | `EVT_VOICE_COMMAND_PLAY_DEAD` | — | 1 | `command_play_dead` | `play_dead` | `play_dead` |
| `audio_direct` | `EVT_VOICE_COMMAND_BRING` | — | 1 | `command_bring` | `bring_object` | `bring_object` |
| `audio_direct` | `EVT_VOICE_COMMAND_FETCH` | — | 1 | `command_fetch` | `fetch_object` | `fetch_object` |
| `audio_direct` | `EVT_VOICE_COMMAND_STOP` | — | 0 | `emergency_stop` | `emergency_stop` | `emergency_stop` |
| `audio_direct` | `EVT_VOICE_COMMAND_COMFORT_DONT_BE_AFRAID` | — | 1 | `command_comfort_dont_be_afraid` | `comfort_soothe` | `comfort_soothe`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_COMFORT_REASSURE` | — | 1 | `command_comfort_reassure` | `comfort_reassure` | `comfort_reassure`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_HURTS` | — | 1 | `command_ask_if_hurts` | `care_inquire` | `care_inquire`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OFFER_HEAD_FOR_PET` | — | 1 | `command_offer_head_for_pet` | `pet_head` | `pet_head`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_SEEK_HUG` | — | 1 | `command_seek_hug` | `hug` | `hug`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_REFUSE` | — | 1 | `command_refuse` | `refuse` | `refuse`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_REFUSE_PLAY` | — | 1 | `command_refuse_play` | `refuse_play` | `refuse_play`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_FIND_DAD` | — | 1 | `command_find_dad` | `find_dad` | `find_dad`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_FIND_MOM` | — | 1 | `command_find_mom` | `find_mom` | `find_mom`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_DANCE` | — | 1 | `command_dance` | `dance` | `dance`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_BRING_TO_ME` | — | 1 | `command_bring_to_me` | `bring_to_me` | `bring_to_me`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_GIVE_TO_ME` | — | 1 | `command_give_to_me` | `give_me` | `give_me`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_GO_GET_IT` | — | 1 | `command_go_get_it` | `go_fetch` | `go_fetch`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_BRING_IT_BACK` | — | 1 | `command_bring_it_back` | `bring_back` | `bring_back`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_FETCH_BALL` | — | 1 | `command_fetch_ball` | `fetch_ball` | `fetch_ball`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_FIND_TOY` | — | 1 | `command_find_toy` | `find_toy` | `find_toy`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_STAY_HOME_ALONE` | — | 1 | `command_stay_home_alone` | `stay_home` | `stay_home`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_WAIT_FOR_OWNER_RETURN` | — | 1 | `command_wait_for_owner_return` | `wait_return` | `wait_return`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_GOING_OUT` | — | 1 | `command_owner_going_out` | `farewell_leave` | `farewell_leave` |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_RETURNED` | — | 1 | `command_owner_returned` | `greet_return` | `greet_return`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_BYE_BYE` | — | 1 | `command_bye_bye` | `farewell_bye` | `farewell_bye`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_GOODBYE` | — | 1 | `command_goodbye` | `farewell_goodbye` | `farewell_goodbye`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_WHAT_DOING` | — | 1 | `command_ask_what_doing` | `report_activity` | `report_activity`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_WHERE_ARE_YOU` | — | 1 | `command_ask_where_are_you` | `report_location` | `report_location`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_WHATS_WRONG` | — | 1 | `command_ask_whats_wrong` | `report_state` | `report_state`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_WHAT_THINKING` | — | 1 | `command_ask_what_thinking` | `respond_thought` | `respond_thought`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_COMFORTABLE` | — | 1 | `command_ask_if_comfortable` | `respond_comfort` | `respond_comfort`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_LIKES` | — | 1 | `command_ask_if_likes` | `respond_like` | `respond_like`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_FUN` | — | 1 | `command_ask_if_fun` | `respond_fun` | `respond_fun`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_UNDERSTANDS` | — | 1 | `command_ask_if_understands` | `respond_understand` | `respond_understand`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_ABILITIES` | — | 1 | `command_ask_abilities` | `show_skill` | `show_skill`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_ASK_IF_LEARNED` | — | 1 | `command_ask_if_learned` | `respond_learned` | `respond_learned`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_EXPRESS_MISS_YOU` | — | 1 | `command_express_miss_you` | `miss_owner` | `miss_owner` |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_TIRED` | — | 1 | `command_owner_tired` | `tired` | `tired`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_ANNOYED` | — | 1 | `command_owner_annoyed` | `annoyed` | `annoyed`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_UNHAPPY` | — | 1 | `command_owner_unhappy` | `unhappy` | `unhappy` |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_BAD_DAY` | — | 1 | `command_owner_bad_day` | `downcast` | `downcast`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_DEPRESSED` | — | 1 | `command_owner_depressed` | `depressed` | `depressed`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_STRESSED` | — | 1 | `command_owner_stressed` | `stressed` | `stressed`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_LONELY` | — | 1 | `command_owner_lonely` | `lonely` | `lonely`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_UNWELL` | — | 1 | `command_owner_unwell` | `unwell` | `unwell`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_HAPPY` | — | 1 | `command_owner_happy` | `cheerful` | `cheerful`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_VERY_HAPPY` | — | 1 | `command_owner_very_happy` | `happy` | `happy`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_FEELING_GREAT` | — | 1 | `command_owner_feeling_great` | `great_form` | `great_form`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_FEELING_EXCELLENT` | — | 1 | `command_owner_feeling_excellent` | `great` | `great`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_RELAXED` | — | 1 | `command_owner_relaxed` | `relaxed` | `relaxed`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_WONDERFUL_DAY` | — | 1 | `command_owner_wonderful_day` | `wonderful_day` | `wonderful_day`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_OWNER_FEELING_LUCKY` | — | 1 | `command_owner_feeling_lucky` | `lucky` | `lucky`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_EAT_MEAL` | — | 1 | `command_eat_meal` | `eat_meal` | `eat_meal`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_EAT_SNACK` | — | 1 | `command_eat_snack` | `eat_snack` | `eat_snack`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_EAT_CANNED_FOOD` | — | 1 | `command_eat_canned_food` | `eat_canned_food` | `eat_canned_food`（缺模板） |
| `audio_direct` | `EVT_VOICE_COMMAND_RESPOND_FOOD_PREFERENCE_QUERY` | — | 1 | `command_respond_food_preference_query` | `respond_food_preference` | `respond_food_preference`（缺模板） |
| `visual_direct` | `EVT_VISION_FALL` | — | 1 | `visual_fall_response` | `respond_person_fall` | `respond_person_fall` |
| `visual_direct` | `EVT_VISION_STOP_GESTURE` | — | 1 | `visual_stop_gesture_response` | `respond_stop_gesture` | `respond_stop_gesture` |
| `need` | `NEED_HUNGER_TRIGGERED` | dog_food | 3 | `eat_normal` | `eatNormally` | `eatNormally` |
| `need` | `NEED_HUNGER_TRIGGERED` | no_dog_food | 3 | `seek_food` | `seekFood` | `seekFood` |
| `need` | `NEED_HUNGER_OVERFLOW` | dog_food | 3 | `eat_excited` | `eatExcitedly` | `eatExcitedly` |
| `need` | `NEED_HUNGER_OVERFLOW` | no_dog_food | 3 | `seek_food_urgent` | `seekFoodUrgently` | `seekFood` |
| `need` | `NEED_BLADDER_TRIGGERED` | — | 2 | `request_elimination` | `barkShortAlert` | `barkShortAlert` |
| `need` | `NEED_SLEEPINESS_TRIGGERED` | — | 2 | `settle_to_sleep` | `sleepOnSide` | `sleepOnSide` |
| `need` | `NEED_SLEEPINESS_OVERFLOW` | — | 2 | `sleep_deep` | `sleepNow` | `sleepNow` |
| `need` | `NEED_CLEANLINESS_TRIGGERED` | — | 3 | `groom_light` | `lickPaws` | `lickPaws` |
| `need` | `NEED_ENERGY_TRIGGERED` | — | 0 | `recover_energy` | `restInPlace` | `restInPlace` |
| `need` | `NEED_ENERGY_OVERFLOW` | — | 0 | `recharge_critical` | `recharge` | `recharge` |
| `need` | `NEED_SOCIAL_TRIGGERED` | human | 4 | `human_attention_interaction` | `seekHumanInteraction` | `seekHumanInteraction` |
| `need` | `NEED_SOCIAL_TRIGGERED` | animal | 4 | `animal_boundary_test` | `testAnimalBoundary` | `testAnimalBoundary` |
| `need` | `NEED_SOCIAL_URGENT` | human | 4 | `social_engage` | `seekInteraction` | `seekInteraction` |
| `need` | `NEED_SOCIAL_URGENT` | animal | 4 | `animal_social_greet` | `greetAnimal` | `greetAnimal` |
| `need` | `NEED_SOCIAL_OVERFLOW` | human | 4 | `human_play_invite` | `inviteHumanToPlay` | `inviteHumanToPlay` |
| `need` | `NEED_SOCIAL_OVERFLOW` | animal | 4 | `animal_play_invite` | `inviteAnimalToPlay` | `inviteAnimalToPlay` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | play_item | 4 | `inspect_familiar_play_item` | `inspectFamiliarPlayItem` | `inspectFamiliarPlayItem` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | trash_can | 4 | `inspect_trash_can` | `inspectTrashCan` | `inspectTrashCan` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | delivery_box | 4 | `inspect_delivery_box` | `inspectDeliveryBox` | `inspectDeliveryBox` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | tissue | 4 | `inspect_tissue` | `inspectTissuePaper` | `inspectTissuePaper` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | door | 4 | `inspect_door` | `inspectDoor` | `inspectDoor` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | dog_food | 4 | `inspect_dog_food` | `inspectDogFood` | `inspectDogFood` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | unfamiliar_object | 4 | `inspect_generic_object` | `inspectObject` | `inspectObject` |
| `need` | `NEED_EXPLORATION_TRIGGERED` | empty | 4 | `explore_space` | `exploreRoom` | `exploreRoom` |

### 有界社交反应

| 事件 | role | 可选情绪表达 | TTL 秒 | cooldown 秒 |
| --- | --- | --- | ---: | ---: |
| `EVT_VOICE_COMMAND_PRAISE` | `social_reaction` | Joy / Excite | 5.0 | 2.0 |
| `EVT_VOICE_COMMAND_SCOLD` | `social_reaction` | Anxiety / Curious / Fear | 5.0 | 2.0 |

这两条反应经专用 mapper 按人物上下文等条件生成有界表达；不是直接把情绪状态值改成某个固定值。

### 情绪状态触发

| signal_event | Lv | 人物目标 | 无人物 | 语音等待的原地表达 |
| --- | ---: | --- | --- | --- |
| `EMO_CALM_TRIGGERED` | 5 | `expressCalmWithHuman` | `expressCalmAlone` | `expressCalmInPlaceWithHuman` |
| `EMO_JOY_TRIGGERED` | 5 | `expressJoyWithHuman` | `expressJoyAlone` | `expressJoyInPlaceWithHuman` |
| `EMO_EXCITE_TRIGGERED` | 5 | `expressExcitementWithHuman` | `expressExcitementAlone` | `expressExcitementInPlaceWithHuman` |
| `EMO_ANXIETY_TRIGGERED` | 5 | `expressAnxietyWithHuman` | `expressAnxietyAlone` | `expressAnxietyInPlaceWithHuman` |
| `EMO_FEAR_TRIGGERED` | 5 | `expressFearWithHuman` | `expressFearAlone` | `expressFearInPlaceWithHuman` |
| `EMO_CURIOUS_TRIGGERED` | 5 | `expressCuriosityWithHuman` | `expressCuriosityAlone` | `expressCuriosityInPlaceWithHuman` |

语音唤醒的内部续接行为 `approach_voice_caller` 来自 `approach_wake_speaker`，不是新的公开语音命令事件。state 恢复与 CLOSED 等生命周期入口不会作为上述普通映射行执行。

## 2 行为到阶段与动作单元

当前 Action 严格接受的模板共 74 个。阶段以实际加载后的顺序列出；同阶段斜线分隔的是候选选项，具体选择以括号中的策略为准。
表中的前置航点仅在启用相应导航适配的部署中生效。随机导航当前固定点池是 A / B / C / D / E；不能据 K 的历史注释推断运行时一定使用地图随机点。

| Action 行为名 | 前置航点 | 有序阶段及候选 Unit | 成功条件 |
| --- | --- | --- | --- |
| `approach_owner` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_APPROACH_OWNER_CLOSER` | `all_required_stages_completed` |
| `approach_voice_caller` | — | `target_approach` (random_one; required=true; abort)：`ACT_INTERACT_APPROACH_VOICE_CALLER` | `all_required_stages_completed` |
| `back_up` | — | `action` (random_one; required=true; abort)：`ACT_BASIC_BACK_UP` | `all_required_stages_completed` |
| `barkShortAlert` | D | `circle` (random_one; required=true; abort)：`ACT_SNIFF_AND_CIRCLE_AT_TOILET_SPOT`<br/>→ `action` (random_one; required=true; abort)：`ACT_SQUAT_AND_ELIMINATE`<br/>→ `exit` (random_one; required=true; abort)：`ACT_SCRATCH_SOIL_OR_GROUND` / `ACT_SNIFF_EXCREMENT` / `ACT_WALK_AWAY_OR_SHAKE_HEAD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD` | `all_required_stages_completed` |
| `bring_object` | — | `action` (random_one; required=true; abort)：`ACT_OBJECT_BRING` | `all_required_stages_completed` |
| `come_to_owner` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_APPROACH_OWNER` | `all_required_stages_completed` |
| `drop_object` | — | `action` (random_one; required=true; abort)：`ACT_OBJECT_DROP` | `all_required_stages_completed` |
| `eatExcitedly` | C | `lower_head` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD`<br/>→ `lie_down` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN`<br/>→ `stand_up` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `lower_head_again` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `waist_twist` (random_one; required=true; abort)：`ACT_TWIST_WAIST_LEFT_RIGHT` | `all_required_stages_completed` |
| `eatNormally` | C | `lower_head` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD`<br/>→ `lie_down` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN`<br/>→ `stand_up` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `lower_head_again` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `waist_twist` (random_one; required=true; abort)：`ACT_TWIST_WAIST_LEFT_RIGHT` | `all_required_stages_completed` |
| `emergency_stop` | — | `action` (random_one; required=true; abort)：`ACT_SYSTEM_EMERGENCY_STOP` | `all_required_stages_completed` |
| `exploreRoom` | — | `explore` (random_one; required=true; abort)：`ACT_TROT_STOP_AND_SNIFF` / `ACT_WALK_SLOWLY_AND_SNIFF_GROUND` / `ACT_CRAWL_THROUGH_LOW_GAP` / `ACT_STAND_AND_SCRATCH_HIGH` / `ACT_PATROL_ALONG_WALL` / `ACT_FIND_PLACE_TO_LIE_DOWN` | `all_required_stages_completed` |
| `expressAnxietyAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_HIDE_SHRINK` / `ACT_PACE` / `ACT_WHIMPER` / `ACT_LICK_SELF` / `ACT_LICK_FACE` | `all_required_stages_completed` |
| `expressAnxietyInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_PAW_LEG` / `ACT_WHINE` / `ACT_SEEK_PETS` | `all_required_stages_completed` |
| `expressAnxietyWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_PAW_LEG` / `ACT_WHINE` / `ACT_SEEK_PETS` | `all_required_stages_completed` |
| `expressCalmAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_GUARD_DOOR` / `ACT_YAWN` / `ACT_STRETCH` / `ACT_PATROL` / `ACT_SPLOOT` | `all_required_stages_completed` |
| `expressCalmInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_CHECK_OWNER` / `ACT_SLEEP_BY_FEET` | `all_required_stages_completed` |
| `expressCalmWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_CHECK_OWNER` / `ACT_SLEEP_BY_FEET` | `all_required_stages_completed` |
| `expressCuriosityAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_NON_INTERACT_EXPLORE` | `all_required_stages_completed` |
| `expressCuriosityInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_INTERACT_EXPLORE` | `all_required_stages_completed` |
| `expressCuriosityWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_INTERACT_EXPLORE` | `all_required_stages_completed` |
| `expressExcitementAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_ZOOMIES` / `ACT_BONE_DANCE` / `ACT_BAT_TOY` / `ACT_SHAKE_TOY` / `ACT_CHASE_TAIL` / `ACT_FETCH_LEASH` | `all_required_stages_completed` |
| `expressExcitementInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_JUMP_PAW` / `ACT_SPIN_FRONT` / `ACT_NIP_PLAYFUL` / `ACT_PLAY_BOW` / `ACT_ZOOMIE_CIRCLE` / `ACT_ASK_CUDDLE` | `all_required_stages_completed` |
| `expressExcitementWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_JUMP_PAW` / `ACT_SPIN_FRONT` / `ACT_NIP_PLAYFUL` / `ACT_PLAY_BOW` / `ACT_ZOOMIE_CIRCLE` / `ACT_ASK_CUDDLE` | `all_required_stages_completed` |
| `expressFearAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_TUCK_TAIL` / `ACT_COVER_EYES` / `ACT_BARK_TENSE` / `ACT_FREEZE_SHAKE` | `all_required_stages_completed` |
| `expressFearInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_HIDE_BEHIND` / `ACT_CLING_LEG` | `all_required_stages_completed` |
| `expressFearWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_HIDE_BEHIND` / `ACT_CLING_LEG` | `all_required_stages_completed` |
| `expressJoyAlone` | 随机：A/B/C/D/E | `expression` (random_one; required=true; abort)：`ACT_WAG_TAIL` / `ACT_COMFY_STRETCH` / `ACT_TROT_BOUNCE` / `ACT_PURR` | `all_required_stages_completed` |
| `expressJoyInPlaceWithHuman` | — | `expression` (random_one; required=true; abort)：`ACT_NUZZLE_HEAD` / `ACT_NUZZLE_BODY` / `ACT_SHOW_BELLY` / `ACT_WINK` / `ACT_FETCH_TOY` / `ACT_LICK` | `all_required_stages_completed` |
| `expressJoyWithHuman` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_NUZZLE_HEAD` / `ACT_NUZZLE_BODY` / `ACT_SHOW_BELLY` / `ACT_WINK` / `ACT_FETCH_TOY` / `ACT_LICK` | `all_required_stages_completed` |
| `farewell_leave` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_OWNER_GOING_OUT` | `all_required_stages_completed` |
| `fetch_object` | — | `action` (random_one; required=true; abort)：`ACT_OBJECT_FETCH` | `all_required_stages_completed` |
| `follow_owner` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_FOLLOW_OWNER` | `all_required_stages_completed` |
| `give_paw` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_GIVE_PAW` | `all_required_stages_completed` |
| `go_home` | A | `navigation` (random_one; required=true; abort)：`ACT_NAV_GO_HOME` | `all_required_stages_completed` |
| `go_out_to_play` | 随机：A/B/C/D/E | `navigation` (random_one; required=true; abort)：`ACT_NAV_GO_OUT_TO_PLAY` | `all_required_stages_completed` |
| `greetAnimal` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `greet` (random_one; required=true; abort)：`ACT_SNIFF_FACE_OR_EARS` / `ACT_SNIFF_BUTT_OR_TAIL` / `ACT_TOUCH_NOSE_OR_HEAD_GENTLY` / `ACT_APPROACH_SLOWLY_SIDEWAYS` / `ACT_LOWER_HEAD_FLOP_EARS_WAG_TAIL` / `ACT_LIE_BESIDE_OTHER_ANIMAL` | `all_required_stages_completed` |
| `high_five` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_HIGH_FIVE` | `all_required_stages_completed` |
| `hold_position` | — | `hold_current_posture` (random_one; required=true; abort)：`ACT_CONTROL_HOLD_POSITION` | `all_required_stages_completed` |
| `inspectDeliveryBox` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_IGNORE_DELIVERY_BOX` / `ACT_SNIFF_DELIVERY_BOX` / `ACT_BITE_DELIVERY_BOX` / `ACT_CARRY_DELIVERY_BOX_TO_PERSON` / `ACT_SCRATCH_DELIVERY_BOX_WITH_PAW` | `all_required_stages_completed` |
| `inspectDogFood` | C | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `lower_head` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD`<br/>→ `lie_down` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN`<br/>→ `stand_up` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `lower_head_again` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `waist_twist` (random_one; required=true; abort)：`ACT_TWIST_WAIST_LEFT_RIGHT` | `all_required_stages_completed` |
| `inspectDoor` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_IGNORE_DOOR` / `ACT_LEAN_AGAINST_DOOR` / `ACT_LIE_BY_DOOR` / `ACT_SCRATCH_DOOR` / `ACT_SNIFF_AROUND_DOOR` | `all_required_stages_completed` |
| `inspectFamiliarPlayItem` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_IGNORE_SLIPPERS_SOCKS_OR_TOY` / `ACT_BITE_AND_SHAKE_SLIPPERS_SOCKS_OR_TOY` / `ACT_POUNCE_ON_SLIPPERS_SOCKS_OR_TOY` / `ACT_CARRY_SLIPPERS_SOCKS_OR_TOY_TO_OWNER` / `ACT_PAW_AT_SLIPPERS_SOCKS_OR_TOY` / `ACT_SNIFF_SLIPPERS_SOCKS_OR_TOY` | `all_required_stages_completed` |
| `inspectObject` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_SNIFF_OBJECT` / `ACT_PUSH_OBJECT_WITH_PAW` / `ACT_SCRATCH_OBJECT_GENTLY` / `ACT_CARRY_AND_HIDE_OBJECT` / `ACT_CARRY_AND_DROP_OBJECT_AGAIN` / `ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH` / `ACT_BARK_AT_OBJECT` / `ACT_KNOCK_OVER_OBJECT` / `ACT_NIBBLE_OBJECT` | `all_required_stages_completed` |
| `inspectTissuePaper` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_IGNORE_TISSUE` / `ACT_SNIFF_TISSUE` / `ACT_SCRATCH_TISSUE_WITH_PAW` / `ACT_CARRY_TISSUE_TO_PERSON` | `all_required_stages_completed` |
| `inspectTrashCan` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `inspect` (random_one; required=true; abort)：`ACT_IGNORE_TRASH_CAN` / `ACT_RUMMAGE_THROUGH_TRASH_CAN` / `ACT_SNIFF_TRASH_CAN` | `all_required_stages_completed` |
| `inviteAnimalToPlay` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `invite` (random_one; required=true; abort)：`ACT_RUN_AWAY_AND_LOOK_BACK` / `ACT_PLAY_BOW` / `ACT_BUMP_OTHER_GENTLY_WITH_RELAXED_BODY` / `ACT_POUNCE_OR_SIDE_HOP_GENTLY` / `ACT_RUN_IN_CIRCLES_OR_CHASE` / `ACT_PAW_GENTLY_AT_OTHER` | `all_required_stages_completed` |
| `inviteHumanToPlay` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `invite` (random_one; required=true; abort)：`ACT_FOLLOW_AND_STAY_CLOSE_TO_OWNER` / `ACT_SIT_IN_FRONT_OF_OWNER_AND_LOOK_UP` / `ACT_PLACE_FRONT_PAWS_ON_OWNER_FOR_ATTENTION` / `ACT_WHINE_OR_VOCALIZE_SOFTLY` / `ACT_NUDGE_OR_RUB_AGAINST_OWNER_HAND` / `ACT_ROLL_OVER_FOR_BELLY_RUB` / `ACT_RUB_AGAINST_LEG_OR_LEAN_ON_OWNER` | `all_required_stages_completed` |
| `lickPaws` | E | `groom` (random_one; required=true; abort)：`ACT_LICK_PAWS_OR_FUR` / `ACT_RUB_BODY_AGAINST_OBJECT` / `ACT_PAW_AT_MUZZLE` / `ACT_SHAKE_OFF_WATER` / `ACT_SCRATCH_EAR_WITH_HIND_LEG` | `all_required_stages_completed` |
| `lie_down` | — | `action` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN` | `all_required_stages_completed` |
| `miss_owner` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_EXPRESS_MISS_YOU` | `all_required_stages_completed` |
| `play_alone` | — | `uwb_roam` (random_one; required=true; abort)：`ACT_UWB_RANDOM_ROAM`<br/>→ `play` (random_one; required=true; abort)：`ACT_GUARD_DOOR` / `ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD` / `ACT_STRETCH` | `all_required_stages_completed` |
| `play_dead` | — | `action` (random_one; required=true; abort)：`ACT_TRICK_PLAY_DEAD` | `all_required_stages_completed` |
| `quiet` | — | `stop_vocalization` (random_one; required=true; abort)：`ACT_CONTROL_QUIET` | `all_required_stages_completed` |
| `recharge` | B | `recharge` (random_one; required=true; abort)：`ACT_RETURN_TO_CHARGER` / `ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER` | `all_required_stages_completed` |
| `respond_owner_call` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_RESPOND_CALL` | `all_required_stages_completed` |
| `respond_person_fall` | — | `safety_stop` (random_one; required=true; abort)：`ACT_PERCEPTION_RESPOND_PERSON_FALL` | `all_required_stages_completed` |
| `respond_stop_gesture` | — | `safety_stop` (random_one; required=true; abort)：`ACT_PERCEPTION_RESPOND_STOP_GESTURE` | `all_required_stages_completed` |
| `restInPlace` | B | `recover` (random_one; required=true; abort)：`ACT_SLOW_DOWN_IN_RESPONSE_TO_OWNER` / `ACT_RETURN_TO_DOG_BED_FOR_CHARGING` | `all_required_stages_completed` |
| `return_to_owner` | — | `action` (random_one; required=true; abort)：`ACT_INTERACT_RETURN_OWNER` | `all_required_stages_completed` |
| `roll_over` | — | `action` (random_one; required=true; abort)：`ACT_TRICK_ROLL_OVER` | `all_required_stages_completed` |
| `seekFood` | C | `lower_head` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD`<br/>→ `lie_down` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN`<br/>→ `stand_up` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `lower_head_again` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `waist_twist` (random_one; required=true; abort)：`ACT_TWIST_WAIST_LEFT_RIGHT` | `all_required_stages_completed` |
| `seekFoodUrgently` | C | `lower_head` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `head_up` (random_one; required=true; abort)：`ACT_RAISE_HEAD`<br/>→ `lie_down` (random_one; required=true; abort)：`ACT_BASIC_LIE_DOWN`<br/>→ `stand_up` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `lower_head_again` (random_one; required=true; abort)：`ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD`<br/>→ `waist_twist` (random_one; required=true; abort)：`ACT_TWIST_WAIST_LEFT_RIGHT` | `all_required_stages_completed` |
| `seekHumanInteraction` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `interact` (random_one; required=true; abort)：`ACT_PAW_AT_OWNER` / `ACT_GENTLY_MOUTH_PANTS_OR_HAND` / `ACT_RUN_IN_CIRCLES_OR_ZOOMIES` / `ACT_CARRY_TOY_AND_WAG_TAIL_IN_FRONT_OF_OWNER` / `ACT_PLAY_BOW` / `ACT_RUN_AWAY_AND_LOOK_BACK` / `ACT_SIDE_HOP_WITH_PLAY_POSTURE` | `all_required_stages_completed` |
| `seekInteraction` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `interact` (random_one; required=true; abort)：`ACT_CARRY_LEASH_TO_OWNER` / `ACT_PAW_AT_BOWL_OR_TREAT_CABINET` / `ACT_WAIT_BY_BOWL_OR_TREAT_CABINET` / `ACT_NUDGE_OWNER_AND_LOOK_AT_FOOD_OR_DOOR` / `ACT_SIT_BY_DOOR_AND_LOOK_BACK_AT_OWNER` / `ACT_CIRCLE_EMPTY_BOWL_OR_WATER_DISH` | `all_required_stages_completed` |
| `sit_down` | — | `action` (random_one; required=true; abort)：`ACT_BASIC_SIT` | `all_required_stages_completed` |
| `sleepNow` | A | `circle` (random_one; required=true; abort)：`ACT_CIRCLE_AROUND`<br/>→ `prepare` (random_one; required=true; abort)：`ACT_SCRATCH_BED_OR_GROUND` / `ACT_STRETCH_BODY` / `ACT_YAWN` / `ACT_SPLoot_LIE_DOWN` / `ACT_LICK_FUR_OR_PAWS`<br/>→ `sleep_pose` (random_one; required=true; abort)：`ACT_SLEEP_ON_SIDE` / `ACT_SLEEP_ON_BACK`<br/>→ `sleeping` (random_one; required=true; abort)：`ACT_FLIP_BODY` / `ACT_WHINE_SOFTLY` / `ACT_TWITCH_OR_KICK_LEGS`<br/>→ `wakeup` (random_one; required=true; abort)：`ACT_GETUP_ROLL` / `ACT_GETUP_STRETCH` / `ACT_GETUP_SIT` | `all_required_stages_completed` |
| `sleepOnSide` | A | `circle` (random_one; required=true; abort)：`ACT_CIRCLE_AROUND`<br/>→ `prepare` (random_one; required=true; abort)：`ACT_SCRATCH_BED_OR_GROUND` / `ACT_STRETCH_BODY` / `ACT_YAWN` / `ACT_SPLoot_LIE_DOWN` / `ACT_LICK_FUR_OR_PAWS`<br/>→ `sleep_pose` (random_one; required=true; abort)：`ACT_SLEEP_CURLED_UP` / `ACT_SLEEP_ON_STOMACH` / `ACT_SLEEP_ON_SIDE_CURLED_UP`<br/>→ `sleeping` (random_one; required=true; abort)：`ACT_FLIP_BODY` / `ACT_WHINE_SOFTLY` / `ACT_TWITCH_OR_KICK_LEGS`<br/>→ `wakeup` (random_one; required=true; abort)：`ACT_GETUP_CRAWL` / `ACT_GETUP_ROLL` / `ACT_GETUP_BOUNCE` / `ACT_GETUP_STRETCH` / `ACT_GETUP_SIT` / `ACT_GETUP_CRAWL` | `all_required_stages_completed` |
| `spin_around` | — | `action` (random_one; required=true; abort)：`ACT_TRICK_SPIN` | `all_required_stages_completed` |
| `stand_still` | — | `ensure_standing` (random_one; required=true; abort)：`ACT_BASIC_STAND`<br/>→ `hold_standing` (random_one; required=true; abort)：`ACT_CONTROL_HOLD_STANDING` | `all_required_stages_completed` |
| `stand_up` | — | `action` (random_one; required=true; abort)：`ACT_BASIC_STAND` | `all_required_stages_completed` |
| `testAnimalBoundary` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `express` (random_one; required=true; abort)：`ACT_BARK_OR_WHINE_BRIEFLY` / `ACT_STOP_OBSERVE_AND_TILT_HEAD` / `ACT_SNIFF_TOWARD_OTHER_ANIMAL` | `all_required_stages_completed` |
| `unhappy` | — | `target_approach` (random_one; required=true; abort)：`ACT_APPROACH_VISUAL_TARGET`<br/>→ `expression` (random_one; required=true; abort)：`ACT_OWNER_UNHAPPY` | `all_required_stages_completed` |
| `wait_in_place` | — | `action` (random_one; required=true; abort)：`ACT_BASIC_WAIT` | `all_required_stages_completed` |
| `walk_to_random_point` | 随机：A/B/C/D/E | `navigation` (random_one; required=true; abort)：`ACT_NAV_WALK_RANDOM` | `all_required_stages_completed` |

## 3 动作单元到控制器

动作目录共 183 个 Unit。以下控制路由通过 ConfigLoader 分别以 lite3 和 go2 计算，已包含底盘计划与 overrides；实际启动还必须安装并启用相应 adapter。
路由名代表接入方向，不代表能力已启用、动作 fidelity 达标或真机成功。Lite3 的 verified、fidelity、enabled 等限制另见 lite3_actions.yaml。
类型为 task 的单元通过任务接口执行；控制器实际方法及取消语义仍由对应适配器实现。

| Unit ID | 类型 | Lite3 有效路由 | Go2 有效路由 |
| --- | --- | --- | --- |
| `ACT_APPROACH_SLOWLY_SIDEWAYS` | `atomic_action` | `lite3` | `go2` |
| `ACT_APPROACH_VISUAL_TARGET` | `task` | `visual_target_approach` | `visual_target_approach` |
| `ACT_ASK_CUDDLE` | `atomic_action` | `lite3` | `go2` |
| `ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER` | `composite_action` | `lite3` | `go2` |
| `ACT_BARK_AT_OBJECT` | `atomic_action` | `lite3` | `go2` |
| `ACT_BARK_OR_WHINE_BRIEFLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_BARK_TENSE` | `atomic_action` | `lite3` | `go2` |
| `ACT_BASIC_BACK_UP` | `atomic_action` | `lite3` | `go2` |
| `ACT_BASIC_LIE_DOWN` | `atomic_action` | `lite3` | `go2` |
| `ACT_BASIC_SIT` | `atomic_action` | `lite3` | `go2` |
| `ACT_BASIC_STAND` | `atomic_action` | `lite3` | `go2` |
| `ACT_BASIC_WAIT` | `atomic_action` | `lite3` | `go2` |
| `ACT_BAT_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_BITE_AND_SHAKE_SLIPPERS_SOCKS_OR_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_BITE_DELIVERY_BOX` | `atomic_action` | `lite3` | `go2` |
| `ACT_BONE_DANCE` | `atomic_action` | `unsupported` | `go2` |
| `ACT_BUMP_OTHER_GENTLY_WITH_RELAXED_BODY` | `atomic_action` | `lite3` | `go2` |
| `ACT_CARRY_AND_DROP_OBJECT_AGAIN` | `composite_action` | `lite3` | `go2` |
| `ACT_CARRY_AND_HIDE_OBJECT` | `composite_action` | `lite3` | `go2` |
| `ACT_CARRY_DELIVERY_BOX_TO_PERSON` | `task` | `lite3` | `go2` |
| `ACT_CARRY_LEASH_TO_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_CARRY_SLIPPERS_SOCKS_OR_TOY_TO_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_CARRY_TISSUE_TO_PERSON` | `task` | `lite3` | `go2` |
| `ACT_CARRY_TOY_AND_WAG_TAIL_IN_FRONT_OF_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_CHASE_TAIL` | `atomic_action` | `lite3` | `go2` |
| `ACT_CHECK_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_CIRCLE_AROUND` | `composite_action` | `lite3` | `go2` |
| `ACT_CIRCLE_EMPTY_BOWL_OR_WATER_DISH` | `atomic_action` | `lite3` | `go2` |
| `ACT_CLING_LEG` | `atomic_action` | `lite3` | `go2` |
| `ACT_COMFY_STRETCH` | `atomic_action` | `lite3` | `go2` |
| `ACT_CONTROL_HOLD_POSITION` | `atomic_action` | `lite3` | `go2` |
| `ACT_CONTROL_HOLD_STANDING` | `atomic_action` | `lite3` | `go2` |
| `ACT_CONTROL_QUIET` | `policy` | `mock` | `mock` |
| `ACT_COVER_EYES` | `atomic_action` | `lite3` | `go2` |
| `ACT_CRAWL_THROUGH_LOW_GAP` | `composite_action` | `lite3` | `go2` |
| `ACT_EXPRESS_MISS_YOU` | `atomic_action` | `lite3` | `go2` |
| `ACT_FETCH_LEASH` | `atomic_action` | `lite3` | `go2` |
| `ACT_FETCH_TOY` | `task` | `lite3` | `go2` |
| `ACT_FIND_PLACE_TO_LIE_DOWN` | `atomic_action` | `lite3` | `go2` |
| `ACT_FLIP_BODY` | `atomic_action` | `lite3` | `go2` |
| `ACT_FOLLOW_AND_STAY_CLOSE_TO_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_FREEZE_SHAKE` | `atomic_action` | `lite3` | `go2` |
| `ACT_GENTLY_MOUTH_PANTS_OR_HAND` | `atomic_action` | `lite3` | `go2` |
| `ACT_GETUP_BOUNCE` | `composite_action` | `lite3` | `go2` |
| `ACT_GETUP_CRAWL` | `composite_action` | `lite3` | `go2` |
| `ACT_GETUP_ROLL` | `composite_action` | `lite3` | `go2` |
| `ACT_GETUP_SIT` | `composite_action` | `lite3` | `go2` |
| `ACT_GETUP_STRETCH` | `composite_action` | `lite3` | `go2` |
| `ACT_GUARD_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_HIDE_BEHIND` | `atomic_action` | `lite3` | `go2` |
| `ACT_HIDE_SHRINK` | `atomic_action` | `lite3` | `go2` |
| `ACT_IGNORE_DELIVERY_BOX` | `policy` | `lite3` | `go2` |
| `ACT_IGNORE_DOOR` | `policy` | `lite3` | `go2` |
| `ACT_IGNORE_SLIPPERS_SOCKS_OR_TOY` | `policy` | `lite3` | `go2` |
| `ACT_IGNORE_TISSUE` | `policy` | `lite3` | `go2` |
| `ACT_IGNORE_TRASH_CAN` | `policy` | `lite3` | `go2` |
| `ACT_INTERACT_APPROACH_OWNER` | `task` | `person_nav_approach` | `person_nav_approach` |
| `ACT_INTERACT_APPROACH_OWNER_CLOSER` | `task` | `person_nav_approach` | `person_nav_approach` |
| `ACT_INTERACT_APPROACH_VOICE_CALLER` | `task` | `person_nav_approach` | `person_nav_approach` |
| `ACT_INTERACT_EXPLORE` | `atomic_action` | `lite3` | `go2` |
| `ACT_INTERACT_FOLLOW_OWNER` | `atomic_action` | `uwb_follow` | `uwb_follow` |
| `ACT_INTERACT_GIVE_PAW` | `atomic_action` | `lite3` | `go2` |
| `ACT_INTERACT_HIGH_FIVE` | `atomic_action` | `lite3` | `go2` |
| `ACT_INTERACT_RESPOND_CALL` | `atomic_action` | `wake_orientation` | `wake_orientation` |
| `ACT_INTERACT_RETURN_OWNER` | `task` | `person_nav_approach` | `person_nav_approach` |
| `ACT_JUMP_PAW` | `atomic_action` | `unsupported` | `go2` |
| `ACT_KNOCK_OVER_OBJECT` | `atomic_action` | `lite3` | `go2` |
| `ACT_LEAN_AGAINST_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_LICK` | `atomic_action` | `lite3` | `go2` |
| `ACT_LICK_FACE` | `atomic_action` | `lite3` | `go2` |
| `ACT_LICK_FUR_OR_PAWS` | `atomic_action` | `lite3` | `go2` |
| `ACT_LICK_PAWS_OR_FUR` | `atomic_action` | `lite3` | `go2` |
| `ACT_LICK_SELF` | `atomic_action` | `lite3` | `go2` |
| `ACT_LIE_BESIDE_OTHER_ANIMAL` | `atomic_action` | `lite3` | `go2` |
| `ACT_LIE_BY_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_LOWER_HEAD_FLOP_EARS_WAG_TAIL` | `composite_action` | `lite3` | `go2` |
| `ACT_NAV_GO_HOME` | `atomic_action` | `behavior_mobility` | `behavior_mobility` |
| `ACT_NAV_GO_OUT_TO_PLAY` | `atomic_action` | `behavior_mobility` | `behavior_mobility` |
| `ACT_NAV_WALK_RANDOM` | `atomic_action` | `behavior_mobility` | `behavior_mobility` |
| `ACT_NIBBLE_OBJECT` | `atomic_action` | `lite3` | `go2` |
| `ACT_NIP_PLAYFUL` | `atomic_action` | `lite3` | `go2` |
| `ACT_NON_INTERACT_EXPLORE` | `atomic_action` | `lite3` | `go2` |
| `ACT_NUDGE_OR_RUB_AGAINST_OWNER_HAND` | `atomic_action` | `lite3` | `go2` |
| `ACT_NUDGE_OWNER_AND_LOOK_AT_FOOD_OR_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_NUZZLE_BODY` | `atomic_action` | `lite3` | `go2` |
| `ACT_NUZZLE_HEAD` | `atomic_action` | `lite3` | `go2` |
| `ACT_OBJECT_BRING` | `atomic_action` | `lite3` | `go2` |
| `ACT_OBJECT_DROP` | `atomic_action` | `lite3` | `go2` |
| `ACT_OBJECT_FETCH` | `atomic_action` | `lite3` | `go2` |
| `ACT_OWNER_GOING_OUT` | `atomic_action` | `lite3` | `go2` |
| `ACT_OWNER_UNHAPPY` | `atomic_action` | `lite3` | `go2` |
| `ACT_PACE` | `atomic_action` | `lite3` | `go2` |
| `ACT_PATROL` | `atomic_action` | `lite3` | `go2` |
| `ACT_PATROL_ALONG_WALL` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_AT_BOWL_OR_TREAT_CABINET` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_AT_MUZZLE` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_AT_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_AT_SLIPPERS_SOCKS_OR_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_GENTLY_AT_OTHER` | `atomic_action` | `lite3` | `go2` |
| `ACT_PAW_LEG` | `atomic_action` | `lite3` | `go2` |
| `ACT_PERCEPTION_RESPOND_PERSON_FALL` | `atomic_action` | `lite3` | `go2` |
| `ACT_PERCEPTION_RESPOND_STOP_GESTURE` | `atomic_action` | `lite3` | `go2` |
| `ACT_PLACE_FRONT_PAWS_ON_OWNER_FOR_ATTENTION` | `atomic_action` | `lite3` | `go2` |
| `ACT_PLAY_BOW` | `atomic_action` | `lite3` | `go2` |
| `ACT_POUNCE_ON_SLIPPERS_SOCKS_OR_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_POUNCE_OR_SIDE_HOP_GENTLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_PURR` | `atomic_action` | `lite3` | `go2` |
| `ACT_PUSH_OBJECT_WITH_PAW` | `atomic_action` | `lite3` | `go2` |
| `ACT_RAISE_HEAD` | `atomic_action` | `lite3` | `go2` |
| `ACT_RETURN_TO_CHARGER` | `task` | `lite3` | `go2` |
| `ACT_RETURN_TO_DOG_BED_FOR_CHARGING` | `atomic_action` | `lite3` | `go2` |
| `ACT_ROLL_OVER_FOR_BELLY_RUB` | `atomic_action` | `lite3` | `go2` |
| `ACT_RUB_AGAINST_LEG_OR_LEAN_ON_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_RUB_BODY_AGAINST_OBJECT` | `atomic_action` | `lite3` | `go2` |
| `ACT_RUMMAGE_THROUGH_TRASH_CAN` | `task` | `lite3` | `go2` |
| `ACT_RUN_AWAY_AND_LOOK_BACK` | `atomic_action` | `lite3` | `go2` |
| `ACT_RUN_IN_CIRCLES_OR_CHASE` | `composite_action` | `lite3` | `go2` |
| `ACT_RUN_IN_CIRCLES_OR_ZOOMIES` | `composite_action` | `lite3` | `go2` |
| `ACT_SCRATCH_BED_OR_GROUND` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_DELIVERY_BOX_WITH_PAW` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_EAR_WITH_HIND_LEG` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_OBJECT_GENTLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_SOIL_OR_GROUND` | `atomic_action` | `lite3` | `go2` |
| `ACT_SCRATCH_TISSUE_WITH_PAW` | `atomic_action` | `lite3` | `go2` |
| `ACT_SEEK_PETS` | `atomic_action` | `lite3` | `go2` |
| `ACT_SHAKE_OFF_WATER` | `atomic_action` | `lite3` | `go2` |
| `ACT_SHAKE_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_SHOW_BELLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_SIDE_HOP_WITH_PLAY_POSTURE` | `atomic_action` | `lite3` | `go2` |
| `ACT_SIT_BY_DOOR_AND_LOOK_BACK_AT_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_SIT_IN_FRONT_OF_OWNER_AND_LOOK_UP` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_BY_FEET` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_CURLED_UP` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_ON_BACK` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_ON_SIDE` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_ON_SIDE_CURLED_UP` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLEEP_ON_STOMACH` | `atomic_action` | `lite3` | `go2` |
| `ACT_SLOW_DOWN_IN_RESPONSE_TO_OWNER` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_AND_CIRCLE_AT_TOILET_SPOT` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_AROUND_DOOR` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_BOWL_AND_WAIT_FOR_FOOD` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_BUTT_OR_TAIL` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_DELIVERY_BOX` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_EXCREMENT` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_FACE_OR_EARS` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_OBJECT` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_SLIPPERS_SOCKS_OR_TOY` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_TISSUE` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_TOWARD_OTHER_ANIMAL` | `atomic_action` | `lite3` | `go2` |
| `ACT_SNIFF_TRASH_CAN` | `atomic_action` | `lite3` | `go2` |
| `ACT_SPIN_FRONT` | `atomic_action` | `lite3` | `go2` |
| `ACT_SPLOOT` | `atomic_action` | `lite3` | `go2` |
| `ACT_SPLoot_LIE_DOWN` | `atomic_action` | `lite3` | `go2` |
| `ACT_SQUAT_AND_ELIMINATE` | `atomic_action` | `lite3` | `go2` |
| `ACT_STAND_AND_SCRATCH_HIGH` | `atomic_action` | `lite3` | `go2` |
| `ACT_STOP_OBSERVE_AND_TILT_HEAD` | `atomic_action` | `lite3` | `go2` |
| `ACT_STRETCH` | `atomic_action` | `lite3` | `go2` |
| `ACT_STRETCH_BODY` | `atomic_action` | `lite3` | `go2` |
| `ACT_SYSTEM_EMERGENCY_STOP` | `atomic_action` | `lite3` | `go2` |
| `ACT_TOUCH_NOSE_OR_HEAD_GENTLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH` | `composite_action` | `lite3` | `go2` |
| `ACT_TRICK_PLAY_DEAD` | `atomic_action` | `lite3` | `go2` |
| `ACT_TRICK_ROLL_OVER` | `atomic_action` | `lite3` | `go2` |
| `ACT_TRICK_SPIN` | `atomic_action` | `lite3` | `go2` |
| `ACT_TROT_BOUNCE` | `atomic_action` | `lite3` | `go2` |
| `ACT_TROT_STOP_AND_SNIFF` | `atomic_action` | `lite3` | `go2` |
| `ACT_TUCK_TAIL` | `atomic_action` | `lite3` | `go2` |
| `ACT_TWIST_WAIST_LEFT_RIGHT` | `atomic_action` | `lite3` | `go2` |
| `ACT_TWITCH_OR_KICK_LEGS` | `atomic_action` | `lite3` | `go2` |
| `ACT_UWB_RANDOM_ROAM` | `atomic_action` | `uwb_roam` | `uwb_roam` |
| `ACT_WAG_TAIL` | `atomic_action` | `lite3` | `go2` |
| `ACT_WAIT_BY_BOWL_OR_TREAT_CABINET` | `atomic_action` | `lite3` | `go2` |
| `ACT_WALK_AWAY_OR_SHAKE_HEAD` | `composite_action` | `lite3` | `go2` |
| `ACT_WALK_SLOWLY_AND_SNIFF_GROUND` | `composite_action` | `lite3` | `go2` |
| `ACT_WHIMPER` | `atomic_action` | `lite3` | `go2` |
| `ACT_WHINE` | `atomic_action` | `lite3` | `go2` |
| `ACT_WHINE_OR_VOCALIZE_SOFTLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_WHINE_SOFTLY` | `atomic_action` | `lite3` | `go2` |
| `ACT_WINK` | `atomic_action` | `lite3` | `go2` |
| `ACT_YAWN` | `atomic_action` | `lite3` | `go2` |
| `ACT_ZOOMIES` | `atomic_action` | `lite3` | `go2` |
| `ACT_ZOOMIE_CIRCLE` | `atomic_action` | `lite3` | `go2` |

## 4 配置来源

- [event_intent_map.yaml](../../modules/behavior/config/event_intent_map.yaml)
- [intent_action_pool.yaml](../../modules/behavior/config/intent_action_pool.yaml)
- [behavior_categories.yaml](../../modules/behavior/config/behavior_categories.yaml)
- [emotion_behavior_map.yaml](../../modules/behavior/config/emotion_behavior_map.yaml)
- [behavior_tree_actions.yaml](../../modules/action/config/behavior_tree_actions.yaml)
- [action_catalog.yaml](../../modules/action/config/action_catalog.yaml)
- [controller_routes.yaml](../../modules/action/config/controller_routes.yaml)
- [lite3_actions.yaml](../../modules/action/config/lite3_actions.yaml)
- [go2_sport.yaml](../../modules/action/config/go2_sport.yaml)
- [navigation_waypoints.yaml](../../modules/action/config/navigation_waypoints.yaml)

新增映射、阶段或底盘计划后同步更新本索引。上述映射逐项对照了 Action 模板，未接通项见下节；执行许可与设备证据不由这个静态检查证明。

## 5 当前未接通的配置映射

静态核对发现 49 条事件路由输出的下游行为名没有对应 Action 模板（共 49 个不同名称）。
已检查 IntentMapper、ActionClientAdapter 和 Action 严格接收逻辑：这里没有自动别名补齐。若通过上游门控并下发这些名字，默认 Action 会以 unsupported_behavior 拒绝；这不说明所有这些输入都必然能通过上游门控。
这份文档记录当前状态，未补写缺失动作或改变机器人行为。后续功能开发应逐项决定复用哪个已有行为，或实现明确的新模板与底盘能力。

| 事件 | 路由 | 缺少的 Action 名称 |
| --- | --- | --- |
| `EVT_VOICE_COMMAND_COMFORT_DONT_BE_AFRAID` | — | `comfort_soothe` |
| `EVT_VOICE_COMMAND_COMFORT_REASSURE` | — | `comfort_reassure` |
| `EVT_VOICE_COMMAND_ASK_IF_HURTS` | — | `care_inquire` |
| `EVT_VOICE_COMMAND_OFFER_HEAD_FOR_PET` | — | `pet_head` |
| `EVT_VOICE_COMMAND_SEEK_HUG` | — | `hug` |
| `EVT_VOICE_COMMAND_REFUSE` | — | `refuse` |
| `EVT_VOICE_COMMAND_REFUSE_PLAY` | — | `refuse_play` |
| `EVT_VOICE_COMMAND_FIND_DAD` | — | `find_dad` |
| `EVT_VOICE_COMMAND_FIND_MOM` | — | `find_mom` |
| `EVT_VOICE_COMMAND_DANCE` | — | `dance` |
| `EVT_VOICE_COMMAND_BRING_TO_ME` | — | `bring_to_me` |
| `EVT_VOICE_COMMAND_GIVE_TO_ME` | — | `give_me` |
| `EVT_VOICE_COMMAND_GO_GET_IT` | — | `go_fetch` |
| `EVT_VOICE_COMMAND_BRING_IT_BACK` | — | `bring_back` |
| `EVT_VOICE_COMMAND_FETCH_BALL` | — | `fetch_ball` |
| `EVT_VOICE_COMMAND_FIND_TOY` | — | `find_toy` |
| `EVT_VOICE_COMMAND_STAY_HOME_ALONE` | — | `stay_home` |
| `EVT_VOICE_COMMAND_WAIT_FOR_OWNER_RETURN` | — | `wait_return` |
| `EVT_VOICE_COMMAND_OWNER_RETURNED` | — | `greet_return` |
| `EVT_VOICE_COMMAND_BYE_BYE` | — | `farewell_bye` |
| `EVT_VOICE_COMMAND_GOODBYE` | — | `farewell_goodbye` |
| `EVT_VOICE_COMMAND_ASK_WHAT_DOING` | — | `report_activity` |
| `EVT_VOICE_COMMAND_ASK_WHERE_ARE_YOU` | — | `report_location` |
| `EVT_VOICE_COMMAND_ASK_WHATS_WRONG` | — | `report_state` |
| `EVT_VOICE_COMMAND_ASK_WHAT_THINKING` | — | `respond_thought` |
| `EVT_VOICE_COMMAND_ASK_IF_COMFORTABLE` | — | `respond_comfort` |
| `EVT_VOICE_COMMAND_ASK_IF_LIKES` | — | `respond_like` |
| `EVT_VOICE_COMMAND_ASK_IF_FUN` | — | `respond_fun` |
| `EVT_VOICE_COMMAND_ASK_IF_UNDERSTANDS` | — | `respond_understand` |
| `EVT_VOICE_COMMAND_ASK_ABILITIES` | — | `show_skill` |
| `EVT_VOICE_COMMAND_ASK_IF_LEARNED` | — | `respond_learned` |
| `EVT_VOICE_COMMAND_OWNER_TIRED` | — | `tired` |
| `EVT_VOICE_COMMAND_OWNER_ANNOYED` | — | `annoyed` |
| `EVT_VOICE_COMMAND_OWNER_BAD_DAY` | — | `downcast` |
| `EVT_VOICE_COMMAND_OWNER_DEPRESSED` | — | `depressed` |
| `EVT_VOICE_COMMAND_OWNER_STRESSED` | — | `stressed` |
| `EVT_VOICE_COMMAND_OWNER_LONELY` | — | `lonely` |
| `EVT_VOICE_COMMAND_OWNER_UNWELL` | — | `unwell` |
| `EVT_VOICE_COMMAND_OWNER_HAPPY` | — | `cheerful` |
| `EVT_VOICE_COMMAND_OWNER_VERY_HAPPY` | — | `happy` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_GREAT` | — | `great_form` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_EXCELLENT` | — | `great` |
| `EVT_VOICE_COMMAND_OWNER_RELAXED` | — | `relaxed` |
| `EVT_VOICE_COMMAND_OWNER_WONDERFUL_DAY` | — | `wonderful_day` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_LUCKY` | — | `lucky` |
| `EVT_VOICE_COMMAND_EAT_MEAL` | — | `eat_meal` |
| `EVT_VOICE_COMMAND_EAT_SNACK` | — | `eat_snack` |
| `EVT_VOICE_COMMAND_EAT_CANNED_FOOD` | — | `eat_canned_food` |
| `EVT_VOICE_COMMAND_RESPOND_FOOD_PREFERENCE_QUERY` | — | `respond_food_preference` |
