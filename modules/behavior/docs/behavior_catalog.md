# 行为完整清单（Behavior Catalog）

> 由 config/ 下所有映射配置自动生成，覆盖行为树 Behavior、音频/视觉/需求/情绪事件映射。

## 概览统计

- 行为树 Behavior（`behaviors.yaml`）：**106** 个
- 音频指令路由（`audio_direct`）：**81** 个
- 音频社交反应（`audio_reaction`）：**2** 个（另含 4 个有界特殊事件）
- 视觉事件路由：**2** 个
- 需求事件：**12** 个（含 routes 分支）
- 情绪事件：**6** 个（6 情绪 × 3 上下文 = 18 个行为）

> 合并窗口：姿态/移动/声音类 `cooldown=0.2s`（执行中才去重，执行完即可再次触发）；
> 情绪类（express* / 社交绑情绪 / PLAY）`cooldown=10s`。

---

## 一、行为树 Behavior 全表（behaviors.yaml）

| behavior_name | Lv | base_priority | timeout | cooldown | 说明 |
|---|---|:---:|:---:|:---:|---|
| `avoid_danger` | 0 | 100 | 5.0 | 1.0 | 躲避危险 |
| `emergency_stop` | 0 | 100 | 5.0 | 0.0 | 紧急停止 |
| `annoyed` | 1 | 80 | 8.0 | 0.2 | 烦躁 |
| `approach_owner` | 1 | 80 | 170.0 | 0.2 | 定位并导航靠近主人 |
| `approach_voice_caller` | 1 | 80 | 160.0 | 0.0 | 单次 SLAM 定位后用 Nav2 靠近已识别唤醒者 |
| `back_up` | 1 | 80 | 6.0 | 0.2 | 后退 |
| `barkShortAlert` | 1 | 80 | 60.0 | 0.2 | 短促吠叫提醒 |
| `bring_back` | 1 | 80 | 20.0 | 0.2 | 叼回来 |
| `bring_object` | 1 | 70 | 20.0 | 0.2 | 取来物体 |
| `bring_to_me` | 1 | 80 | 20.0 | 0.2 | 拿给我 |
| `care_inquire` | 1 | 80 | 5.0 | 0.2 | 关怀(疼不疼) |
| `cheerful` | 1 | 80 | 5.0 | 0.2 | 心情好 |
| `come_to_owner` | 1 | 80 | 170.0 | 0.2 | 定位并导航到主人身边 |
| `comfort_reassure` | 1 | 80 | 5.0 | 0.2 | 安抚(没事没事) |
| `comfort_soothe` | 1 | 80 | 5.0 | 0.2 | 安抚(不怕不怕) |
| `dance` | 1 | 80 | 10.0 | 0.2 | 跳舞 |
| `depressed` | 1 | 80 | 8.0 | 0.2 | 抑郁 |
| `downcast` | 1 | 80 | 8.0 | 0.2 | 低落 |
| `drop_object` | 1 | 80 | 3.0 | 0.2 | 放下物体 |
| `eat_canned_food` | 1 | 80 | 30.0 | 0.2 | 吃罐罐 |
| `eat_meal` | 1 | 80 | 30.0 | 0.2 | 吃饭 |
| `eat_snack` | 1 | 80 | 30.0 | 0.2 | 吃零食 |
| `excretion_request` | 1 | 95 | 60.0 | 0.0 | 排泄请求 |
| `farewell_bye` | 1 | 80 | 15.0 | 0.2 | 拜拜 |
| `farewell_goodbye` | 1 | 80 | 15.0 | 0.2 | 再见 |
| `farewell_leave` | 1 | 80 | 15.0 | 0.2 | 告别(主人出门) |
| `fetch_ball` | 1 | 80 | 20.0 | 0.2 | 捡球 |
| `fetch_object` | 1 | 70 | 30.0 | 0.2 | 捡回物体 |
| `find_dad` | 1 | 80 | 20.0 | 0.2 | 找爸爸 |
| `find_mom` | 1 | 80 | 20.0 | 0.2 | 找妈妈 |
| `find_toy` | 1 | 80 | 20.0 | 0.2 | 找玩具 |
| `follow_owner` | 1 | 80 | 0.0 | 0.2 | 一个持续到取消的 UWB 跟随 Goal |
| `give_me` | 1 | 80 | 20.0 | 0.2 | 给我 |
| `give_paw` | 1 | 75 | 5.0 | 0.2 | 握手 |
| `go_back` | 1 | 70 | 6.0 | 0.2 | 后退走 |
| `go_fetch` | 1 | 80 | 20.0 | 0.2 | 去拿 |
| `go_home` | 1 | 80 | 60.0 | 0.2 | 回家 |
| `play_alone` | 1 | 80 | 0.0 | 0.2 | 同一 Goal 内循环 UWB 随机到点、停稳和玩耍姿态 |
| `go_out_to_play` | 1 | 80 | 50.0 | 0.2 | 出去玩 |
| `great` | 1 | 80 | 5.0 | 0.2 | 特别棒 |
| `great_form` | 1 | 80 | 5.0 | 0.2 | 状态好 |
| `greet_return` | 1 | 80 | 15.0 | 0.2 | 迎接归来 |
| `happy` | 1 | 80 | 5.0 | 0.2 | 开心 |
| `high_five` | 1 | 75 | 5.0 | 0.2 | 击掌 |
| `hold_position` | 1 | 80 | 10.0 | 0.2 | 保持位置 |
| `hug` | 1 | 80 | 5.0 | 0.2 | 拥抱 |
| `lickPaws` | 1 | 80 | 15.0 | 0.2 | 舔爪子 |
| `lie_down` | 1 | 80 | 5.0 | 0.2 | 躺下 |
| `lonely` | 1 | 80 | 8.0 | 0.2 | 孤独 |
| `look_at_owner_brief` | 1 | 80 | 5.0 | 0.2 | 短暂看向主人 |
| `lucky` | 1 | 80 | 5.0 | 0.2 | 幸运 |
| `miss_owner` | 1 | 80 | 8.0 | 0.2 | 想念主人 |
| `pet_head` | 1 | 80 | 5.0 | 0.2 | 摸头回应 |
| `play_dead` | 1 | 70 | 8.0 | 0.2 | 装死 |
| `quiet` | 1 | 80 | 3.0 | 0.2 | 安静 |
| `refuse` | 1 | 80 | 5.0 | 0.2 | 拒绝 |
| `refuse_play` | 1 | 80 | 5.0 | 0.2 | 拒绝玩耍 |
| `relaxed` | 1 | 80 | 5.0 | 0.2 | 轻松 |
| `report_activity` | 1 | 80 | 5.0 | 0.2 | 回应在干嘛 |
| `report_location` | 1 | 80 | 5.0 | 0.2 | 回应位置 |
| `report_state` | 1 | 80 | 5.0 | 0.2 | 回应状态 |
| `respond_comfort` | 1 | 80 | 5.0 | 0.2 | 回应舒适 |
| `respond_food_preference` | 1 | 80 | 5.0 | 0.2 | 回应想吃什么 |
| `respond_fun` | 1 | 80 | 5.0 | 0.2 | 回应好玩 |
| `respond_hungry_no` | 1 | 80 | 5.0 | 0.2 | 表示不饿 |
| `respond_hungry_yes` | 1 | 80 | 5.0 | 0.2 | 表示饿 |
| `respond_learned` | 1 | 80 | 5.0 | 0.2 | 回应学会 |
| `respond_like` | 1 | 80 | 5.0 | 0.2 | 回应喜欢 |
| `respond_owner_call` | 1 | 80 | 8.0 | 0.0 | 响应主人呼唤(朝向声源) |
| `respond_person_fall` | 1 | 80 | 8.0 | 1.0 | 响应人摔倒 |
| `respond_stop_gesture` | 1 | 80 | 8.0 | 1.0 | 响应停止手势 |
| `respond_thought` | 1 | 80 | 5.0 | 0.2 | 回应想法 |
| `respond_understand` | 1 | 80 | 5.0 | 0.2 | 回应听懂 |
| `respond_want_eat_no` | 1 | 80 | 5.0 | 0.2 | 不想吃 |
| `respond_want_eat_yes` | 1 | 80 | 5.0 | 0.2 | 想吃 |
| `return_to_owner` | 1 | 80 | 170.0 | 0.2 | 定位并导航回到主人身边 |
| `roll_over` | 1 | 70 | 6.0 | 0.2 | 打滚 |
| `show_skill` | 1 | 80 | 5.0 | 0.2 | 展示技能 |
| `sit_down` | 1 | 80 | 5.0 | 0.2 | 坐下 |
| `sleepOnSide` | 1 | 80 | 120.0 | 0.2 | 侧躺睡 |
| `sleep_request` | 1 | 90 | 120.0 | 0.0 | 睡眠请求 |
| `spin_around` | 1 | 70 | 6.0 | 0.2 | 转圈 |
| `stand_still` | 1 | 80 | 10.0 | 0.2 | 站定 |
| `stand_up` | 1 | 80 | 5.0 | 0.2 | 站起来 |
| `stay_home` | 1 | 80 | 15.0 | 0.2 | 留守 |
| `stressed` | 1 | 80 | 8.0 | 0.2 | 压力 |
| `tired` | 1 | 80 | 8.0 | 0.2 | 疲惫 |
| `unhappy` | 1 | 80 | 8.0 | 0.2 | 不开心 |
| `unwell` | 1 | 80 | 8.0 | 0.2 | 不适 |
| `wait_in_place` | 1 | 75 | 30.0 | 0.2 | 原地等待 |
| `wait_return` | 1 | 80 | 15.0 | 0.2 | 等主人回来 |
| `walk_to_random_point` | 1 | 80 | 50.0 | 0.2 | 走到随机点 |
| `wonderful_day` | 1 | 80 | 5.0 | 0.2 | 好日子 |
| `inspect_environment_change` | 2 | 60 | 5.0 | 1.0 | 检查环境变化 |
| `look_at_sound_source` | 2 | 65 | 3.0 | 0.5 | 看向声源 |
| `respond_touch_head` | 2 | 75 | 5.0 | 1.0 | 响应摸头 |
| `respond_wakeup_word` | 2 | 80 | 6.0 | 1.0 | 响应唤醒词 |
| `clean_self` | 3 | 60 | 15.0 | 3.0 | 自我清洁 |
| `seek_food_or_water` | 3 | 70 | 30.0 | 5.0 | 寻找食物/水 |
| `explore_environment` | 4 | 50 | 25.0 | 3.0 | 探索环境 |
| `seek_social_interaction` | 4 | 60 | 20.0 | 5.0 | 寻求社交互动 |
| `express_curiosity` | 5 | 45 | 4.0 | 1.0 | 表达好奇 |
| `express_fear` | 5 | 50 | 8.0 | 2.0 | 表达恐惧 |
| `express_happy` | 5 | 50 | 5.0 | 1.0 | 表达开心 |
| `idle_look_around` | 6 | 30 | 10.0 | 0.0 | 空闲环顾 |
| `idle_rest` | 6 | 25 | 30.0 | 0.0 | 空闲休息 |

---

## 二、音频事件 → 行为（audio_direct）

| event_type | command_id | 短语 | intent | behavior_name |
|---|---|---|---|---|
| `EVT_VOICE_COMMAND_APPROACH` | `CMD_APPROACH` | 靠近点 | command_approach | `approach_owner` |
| `EVT_VOICE_COMMAND_ASK_ABILITIES` | `CMD_ASK_ABILITIES` | 你会什么 | command_ask_abilities | `show_skill` |
| `EVT_VOICE_COMMAND_ASK_IF_COMFORTABLE` | `CMD_ASK_IF_COMFORTABLE` | 舒服吗 | command_ask_if_comfortable | `respond_comfort` |
| `EVT_VOICE_COMMAND_ASK_IF_FUN` | `CMD_ASK_IF_FUN` | 好玩吗 | command_ask_if_fun | `respond_fun` |
| `EVT_VOICE_COMMAND_ASK_IF_HURTS` | `CMD_ASK_IF_HURTS` | 疼不疼 | command_ask_if_hurts | `care_inquire` |
| `EVT_VOICE_COMMAND_ASK_IF_LEARNED` | `CMD_ASK_IF_LEARNED` | 你学会了吗 | command_ask_if_learned | `respond_learned` |
| `EVT_VOICE_COMMAND_ASK_IF_LIKES` | `CMD_ASK_IF_LIKES` | 喜欢吗 | command_ask_if_likes | `respond_like` |
| `EVT_VOICE_COMMAND_ASK_IF_UNDERSTANDS` | `CMD_ASK_IF_UNDERSTANDS` | 你听得懂吗 | command_ask_if_understands | `respond_understand` |
| `EVT_VOICE_COMMAND_ASK_WHATS_WRONG` | `CMD_ASK_WHATS_WRONG` | 你怎么了 | command_ask_whats_wrong | `report_state` |
| `EVT_VOICE_COMMAND_ASK_WHAT_DOING` | `CMD_ASK_WHAT_DOING` | 你在干嘛 | command_ask_what_doing | `report_activity` |
| `EVT_VOICE_COMMAND_ASK_WHAT_THINKING` | `CMD_ASK_WHAT_THINKING` | 你想什么 | command_ask_what_thinking | `respond_thought` |
| `EVT_VOICE_COMMAND_ASK_WHERE_ARE_YOU` | `CMD_ASK_WHERE_ARE_YOU` | 你在哪里 | command_ask_where_are_you | `report_location` |
| `EVT_VOICE_COMMAND_BACK_UP` | `CMD_BACK_UP` | 退后 | command_back_up | `back_up` |
| `EVT_VOICE_COMMAND_BRING` | `CMD_BRING_OBJECT` | 拿给我(兼容) | command_bring | `bring_object` |
| `EVT_VOICE_COMMAND_BRING_IT_BACK` | `CMD_BRING_IT_BACK` | 叼回来 | command_bring_it_back | `bring_back` |
| `EVT_VOICE_COMMAND_BRING_TO_ME` | `CMD_BRING_TO_ME` | 拿给我 | command_bring_to_me | `bring_to_me` |
| `EVT_VOICE_COMMAND_BYE_BYE` | `CMD_BYE_BYE` | 拜拜 | command_bye_bye | `farewell_bye` |
| `EVT_VOICE_COMMAND_CLEAN` | `CMD_CLEAN` | 擦一擦手/擦一擦脚 | command_clean | `lickPaws` |
| `EVT_VOICE_COMMAND_COME` | `CMD_COME_HERE` | 过来/来/回来 | command_come_here | `come_to_owner` |
| `EVT_VOICE_COMMAND_COMFORT_DONT_BE_AFRAID` | `CMD_COMFORT_DONT_BE_AFRAID` | 不怕不怕 | command_comfort_dont_be_afraid | `comfort_soothe` |
| `EVT_VOICE_COMMAND_COMFORT_REASSURE` | `CMD_COMFORT_REASSURE` | 没事没事 | command_comfort_reassure | `comfort_reassure` |
| `EVT_VOICE_COMMAND_DANCE` | `CMD_DANCE` | 跳个舞 | command_dance | `dance` |
| `EVT_VOICE_COMMAND_DROP` | `CMD_SPIT` | 放下/松开/松口/张嘴 | command_spit_out | `drop_object` |
| `EVT_VOICE_COMMAND_EAT_CANNED_FOOD` | `CMD_EAT_CANNED_FOOD` | 吃罐罐 | command_eat_canned_food | `eat_canned_food` |
| `EVT_VOICE_COMMAND_EAT_MEAL` | `CMD_EAT_MEAL` | 吃饭 | command_eat_meal | `eat_meal` |
| `EVT_VOICE_COMMAND_EAT_SNACK` | `CMD_EAT_SNACK` | 吃零食 | command_eat_snack | `eat_snack` |
| `EVT_VOICE_COMMAND_EXPRESS_MISS_YOU` | `CMD_EXPRESS_MISS_YOU` | 我好想你 | command_express_miss_you | `63
` |
| `EVT_VOICE_COMMAND_FETCH` | `CMD_FETCH_OBJECT` | 捡回(兼容) | command_fetch | `fetch_object` |
| `EVT_VOICE_COMMAND_FETCH_BALL` | `CMD_FETCH_BALL` | 捡球 | command_fetch_ball | `fetch_ball` |
| `EVT_VOICE_COMMAND_FIND_DAD` | `CMD_FIND_DAD` | 去找爸爸 | command_find_dad | `find_dad` |
| `EVT_VOICE_COMMAND_FIND_MOM` | `CMD_FIND_MOM` | 去找妈妈 | command_find_mom | `find_mom` |
| `EVT_VOICE_COMMAND_FIND_TOY` | `CMD_FIND_TOY` | 找玩具 | command_find_toy | `find_toy` |
| `EVT_VOICE_COMMAND_FOLLOW` | `CMD_FOLLOW` | 跟着我/跟我走 | command_follow | `follow_owner` |
| `EVT_VOICE_COMMAND_GIVE_TO_ME` | `CMD_GIVE_TO_ME` | 给我 | command_give_to_me | `give_me` |
| `EVT_VOICE_COMMAND_GOODBYE` | `CMD_GOODBYE` | 再见 | command_goodbye | `farewell_goodbye` |
| `EVT_VOICE_COMMAND_GO_GET_IT` | `CMD_GO_GET_IT` | 去拿 | command_go_get_it | `go_fetch` |
| `EVT_VOICE_COMMAND_GO_HOME` | `CMD_GO_HOME` | 回家 | command_go_home | `go_home` |
| `EVT_VOICE_COMMAND_PLAY_ALONE` | `CMD_PLAY_ALONE` | 自己去玩吧 | command_play_alone | `play_alone` |
| `EVT_VOICE_COMMAND_GO_OUT` | `CMD_GO_OUT` | 出去玩/出去溜溜 | command_go_out | `go_out_to_play` |
| `EVT_VOICE_COMMAND_HIGH_FIVE` | `CMD_FIVE` | 击掌/击个掌/拍手 | command_high_five | `high_five` |
| `EVT_VOICE_COMMAND_HOLD_POSITION` | `CMD_HOLD_POSITION` | 别动/等着/停/不准动 | command_hold_position | `hold_position` |
| `EVT_VOICE_COMMAND_LIE_DOWN` | `CMD_LIE_DOWN` | 趴下/躺下 | command_lie_down | `lie_down` |
| `EVT_VOICE_COMMAND_OFFER_HEAD_FOR_PET` | `CMD_OFFER_HEAD_FOR_PET` | 摸摸头 | command_offer_head_for_pet | `pet_head` |
| `EVT_VOICE_COMMAND_OWNER_ANNOYED` | `CMD_OWNER_ANNOYED` | 我有点烦/烦死了 | command_owner_annoyed | `annoyed` |
| `EVT_VOICE_COMMAND_OWNER_BAD_DAY` | `CMD_OWNER_BAD_DAY` | 过得不太顺利 | command_owner_bad_day | `downcast` |
| `EVT_VOICE_COMMAND_OWNER_DEPRESSED` | `CMD_OWNER_DEPRESSED` | 我要抑郁了/心情不好 | command_owner_depressed | `depressed` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_EXCELLENT` | `CMD_OWNER_FEELING_EXCELLENT` | 特别棒 | command_owner_feeling_excellent | `great` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_GREAT` | `CMD_OWNER_FEELING_GREAT` | 状态特别好 | command_owner_feeling_great | `great_form` |
| `EVT_VOICE_COMMAND_OWNER_FEELING_LUCKY` | `CMD_OWNER_FEELING_LUCKY` | 太幸运 | command_owner_feeling_lucky | `lucky` |
| `EVT_VOICE_COMMAND_OWNER_GOING_OUT` | `CMD_OWNER_GOING_OUT` | 我要出门了 | command_owner_going_out | `farewell_leave` |
| `EVT_VOICE_COMMAND_OWNER_HAPPY` | `CMD_OWNER_HAPPY` | 心情美美的 | command_owner_happy | `cheerful` |
| `EVT_VOICE_COMMAND_OWNER_LONELY` | `CMD_OWNER_LONELY` | 我好孤独 | command_owner_lonely | `lonely` |
| `EVT_VOICE_COMMAND_OWNER_RELAXED` | `CMD_OWNER_RELAXED` | 浑身轻松 | command_owner_relaxed | `relaxed` |
| `EVT_VOICE_COMMAND_OWNER_RETURNED` | `CMD_OWNER_RETURNED` | 我回来了 | command_owner_returned | `greet_return` |
| `EVT_VOICE_COMMAND_OWNER_STRESSED` | `CMD_OWNER_STRESSED` | 压力好大 | command_owner_stressed | `stressed` |
| `EVT_VOICE_COMMAND_OWNER_TIRED` | `CMD_OWNER_TIRED` | 我累了/好累 | command_owner_tired | `tired` |
| `EVT_VOICE_COMMAND_OWNER_UNHAPPY` | `CMD_OWNER_UNHAPPY` | 今天不开心/不得劲 | command_owner_unhappy | `unhappy` |
| `EVT_VOICE_COMMAND_OWNER_UNWELL` | `CMD_OWNER_UNWELL` | 我头疼/不舒服 | command_owner_unwell | `unwell` |
| `EVT_VOICE_COMMAND_OWNER_VERY_HAPPY` | `CMD_OWNER_VERY_HAPPY` | 很开心/很高兴 | command_owner_very_happy | `happy` |
| `EVT_VOICE_COMMAND_OWNER_WONDERFUL_DAY` | `CMD_OWNER_WONDERFUL_DAY` | 好日子 | command_owner_wonderful_day | `wonderful_day` |
| `EVT_VOICE_COMMAND_PLAY_DEAD` | `CMD_DEAD` | biu/装死 | command_play_dead | `play_dead` |
| `EVT_VOICE_COMMAND_QUIET` | `CMD_QUIET` | 安静/闭嘴/别叫/不许叫 | command_quiet | `quiet` |
| `EVT_VOICE_COMMAND_REFUSE` | `CMD_REFUSE` | 我不要 | command_refuse | `refuse` |
| `EVT_VOICE_COMMAND_REFUSE_PLAY` | `CMD_REFUSE_PLAY` | 我不玩 | command_refuse_play | `refuse_play` |
| `EVT_VOICE_COMMAND_RESPOND_FOOD_PREFERENCE_QUERY` | `CMD_RESPOND_FOOD_PREFERENCE_QUERY` | 你想吃什么 | command_respond_food_preference_query | `respond_food_preference` |
| `EVT_VOICE_COMMAND_RETURN` | `CMD_BACK` | 回来(兼容) | command_retrieve | `return_to_owner` |
| `EVT_VOICE_COMMAND_ROLL_OVER` | `CMD_ROLL` | 翻滚 | command_roll | `roll_over` |
| `EVT_VOICE_COMMAND_SEEK_HUG` | `CMD_SEEK_HUG` | 抱抱 | command_seek_hug | `hug` |
| `EVT_VOICE_COMMAND_SHAKE_HAND` | `CMD_HAND` | 握手/握个手/抬手 | command_handshake | `give_paw` |
| `EVT_VOICE_COMMAND_SIT` | `CMD_SIT` | 坐/坐下/蹲下 | command_sit | `sit_down` |
| `EVT_VOICE_COMMAND_SLEEP` | `CMD_SLEEP` | 睡觉/睡吧/去睡/休息 | command_sleep | `sleepOnSide` |
| `EVT_VOICE_COMMAND_SPIN` | `CMD_SPIN` | 转圈 | command_spin | `spin_around` |
| `EVT_VOICE_COMMAND_STAND_STILL` | `CMD_STAND_STILL` | 站好/站着 | command_stand_still | `stand_still` |
| `EVT_VOICE_COMMAND_STAND_UP` | `CMD_STAND_UP` | 起来/站起来 | command_stand_up | `stand_up` |
| `EVT_VOICE_COMMAND_STAY_HOME_ALONE` | `CMD_STAY_HOME_ALONE` | 你自己在家 | command_stay_home_alone | `stay_home` |
| `EVT_VOICE_COMMAND_STOP` | `CMD_STOP` | 停(急停) | emergency_stop | `emergency_stop` |
| `EVT_VOICE_COMMAND_TOILET` | `CMD_TOILET` | 去尿尿/去便便 | command_toilet | `barkShortAlert` |
| `EVT_VOICE_COMMAND_WAIT` | `CMD_WAIT` | 等(兼容) | command_wait | `wait_in_place` |
| `EVT_VOICE_COMMAND_WAIT_FOR_OWNER_RETURN` | `CMD_WAIT_FOR_OWNER_RETURN` | 等我回来 | command_wait_for_owner_return | `wait_return` |
| `EVT_VOICE_COMMAND_WALK` | `CMD_WALK` | 走/去 | command_walk | `walk_to_random_point` |
| `EVT_VOICE_WAKEUP` | `—` | 唤醒词 | orient_to_sound | `respond_owner_call` |

### 词库社交反应（audio_reaction）

| event_type | 处理 |
|---|---|
| `EVT_VOICE_COMMAND_PRAISE` | Lv1 一次性愉悦/兴奋反应；活跃语音会话内使用 `expressJoyInPlaceWithHuman`/`expressExcitementInPlaceWithHuman` |
| `EVT_VOICE_COMMAND_SCOLD` | Lv1 一次性焦虑/好奇/恐惧反应；活跃语音会话内使用对应 `*InPlaceWithHuman` |

`EVT_VOICE_COMMAND_CALL_NAME` 仍是纯社交昵称通知，不进入候选池。

### 有界特殊事件（ros_node 处理）

| event_type | 处理 |
|---|---|
| `EVT_VOICE_COMMAND_PLAY` | 绑定兴奋 `expressExcitement` |
| `EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY` | Hunger>70 → `respond_hungry_yes`，否则 `respond_hungry_no` |
| `EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY` | Hunger>70 → `respond_want_eat_yes`，否则 `respond_want_eat_no` |
| `EVT_VOICE_COMMAND_RESPOND_EATING_QUERY` | 进食中打断→`look_at_owner_brief`→恢复；否则直接 `look_at_owner_brief` |

---

## 三、视觉事件 → 行为（visual_direct）

| event_type | behavior_name | Lv | sub_priority |
|---|---|:---:|:---:|
| `EVT_VISION_FALL` | `respond_person_fall` | 1 | 12 |
| `EVT_VISION_STOP_GESTURE` | `respond_stop_gesture` | 1 | 12 |

---

## 四、需求事件 → 语义行为（need）

| 事件 | 路由 | 语义 behavior_name | intent |
|---|---|---|---|
| `NEED_BLADDER_TRIGGERED` | — | `barkShortAlert` | request_elimination |
| `NEED_CLEANLINESS_TRIGGERED` | — | `lickPaws` | groom_light |
| `NEED_ENERGY_OVERFLOW` | — | `recharge` | recharge_critical |
| `NEED_ENERGY_TRIGGERED` | — | `restInPlace` | recover_energy |
| `NEED_EXPLORATION_TRIGGERED` | play_item | `inspectFamiliarPlayItem` | inspect_familiar_play_item |
| `NEED_EXPLORATION_TRIGGERED` | trash_can | `inspectTrashCan` | inspect_trash_can |
| `NEED_EXPLORATION_TRIGGERED` | delivery_box | `inspectDeliveryBox` | inspect_delivery_box |
| `NEED_EXPLORATION_TRIGGERED` | tissue | `inspectTissuePaper` | inspect_tissue |
| `NEED_EXPLORATION_TRIGGERED` | door | `inspectDoor` | inspect_door |
| `NEED_EXPLORATION_TRIGGERED` | dog_food | `inspectDogFood` | inspect_dog_food |
| `NEED_EXPLORATION_TRIGGERED` | unfamiliar_object | `inspectObject` | inspect_generic_object |
| `NEED_EXPLORATION_TRIGGERED` | empty | `exploreRoom` | explore_space |
| `NEED_HUNGER_OVERFLOW` | dog_food | `eatExcitedly` | eat_excited |
| `NEED_HUNGER_OVERFLOW` | no_dog_food | `seekFoodUrgently` | seek_food_urgent |
| `NEED_HUNGER_TRIGGERED` | dog_food | `eatNormally` | eat_normal |
| `NEED_HUNGER_TRIGGERED` | no_dog_food | `seekFood` | seek_food |
| `NEED_SLEEPINESS_OVERFLOW` | — | `sleepNow` | sleep_deep |
| `NEED_SLEEPINESS_TRIGGERED` | — | `sleepOnSide` | settle_to_sleep |
| `NEED_SOCIAL_OVERFLOW` | human | `inviteHumanToPlay` | human_play_invite |
| `NEED_SOCIAL_OVERFLOW` | animal | `inviteAnimalToPlay` | animal_play_invite |
| `NEED_SOCIAL_TRIGGERED` | human | `seekHumanInteraction` | human_attention_interaction |
| `NEED_SOCIAL_TRIGGERED` | animal | `testAnimalBoundary` | animal_boundary_test |
| `NEED_SOCIAL_URGENT` | human | `seekInteraction` | social_engage |
| `NEED_SOCIAL_URGENT` | animal | `greetAnimal` | animal_social_greet |

---

## 五、情绪事件 → 行为（emotion）

| 事件 | 情绪 | human | voice_waiting | solo |
|---|---|---|---|---|
| `EMO_ANXIETY_TRIGGERED` | anxiety | `expressAnxietyWithHuman` | `expressAnxietyInPlaceWithHuman` | `expressAnxietyAlone` |
| `EMO_CALM_TRIGGERED` | calm | `expressCalmWithHuman` | `expressCalmInPlaceWithHuman` | `expressCalmAlone` |
| `EMO_CURIOUS_TRIGGERED` | curiosity | `expressCuriosityWithHuman` | `expressCuriosityInPlaceWithHuman` | `expressCuriosityAlone` |
| `EMO_EXCITE_TRIGGERED` | excitement | `expressExcitementWithHuman` | `expressExcitementInPlaceWithHuman` | `expressExcitementAlone` |
| `EMO_FEAR_TRIGGERED` | fear | `expressFearWithHuman` | `expressFearInPlaceWithHuman` | `expressFearAlone` |
| `EMO_JOY_TRIGGERED` | joy | `expressJoyWithHuman` | `expressJoyInPlaceWithHuman` | `expressJoyAlone` |

---

## 附录：唯一 behavior_name 统计

跨所有配置共 **151** 个唯一 behavior_name（含语义行为与情绪上下文行为）。
