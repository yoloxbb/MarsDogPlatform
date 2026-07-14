# 事件-行为对照表

从 YAML 配置直接生成，反映当前系统实际映射。

---

## 情绪事件 → 行为 (全部 Lv.5, result_mapping=null)

| 事件 | Behavior | Level | Variant |
|------|----------|-------|---------|
| EMO_CALM_NORMAL | `expressCalm` | LOW | calm_low |
| EMO_CALM_HIGH | `expressCalm` | HIGH | calm_high |
| EMO_JOY_LOW | `expressJoy` | LOW | joy_low |
| EMO_JOY_MID | `expressJoy` | MID | joy_mid |
| EMO_JOY_HIGH | `expressJoy` | HIGH | joy_high |
| EMO_EXCITE_LOW | `expressExcitement` | LOW | excitement_low |
| EMO_EXCITE_HIGH | `expressExcitement` | HIGH | excitement_high |
| EMO_ANXIETY_LOW | `expressAnxiety` | LOW | anxiety_low |
| EMO_ANXIETY_HIGH | `expressAnxiety` | HIGH | anxiety_high |
| EMO_FEAR_LOW | `expressFear` | LOW | fear_low |
| EMO_FEAR_HIGH | `expressFear` | HIGH | fear_high |
| EMO_CURIOUS_LOW | `expressCuriosity` | LOW | curiosity_low |
| EMO_CURIOUS_HIGH | `expressCuriosity` | HIGH | curiosity_high |

## 需求事件 → 行为

| 事件 | Behavior | Lv | Variant | result_mapping |
|------|----------|:--:|------|------|
| NEED_HUNGER_TRIGGERED | `eatNormally` | 3 | — | seek_food_or_water |
| NEED_HUNGER_OVERFLOW | `eatExcitedly` | 3 | — | seek_food_or_water |
| NEED_BLADDER_TRIGGERED | `defecate` | 2 | — | excretion_request |
| NEED_BLADDER_OVERFLOW | `defecate` | 2 | — | excretion_request |
| NEED_SLEEPINESS_TRIGGERED | `sleepNow` | 2 | shallow | sleep_request |
| NEED_SLEEPINESS_OVERFLOW | `sleepNow` | 2 | deep | sleep_request |
| NEED_CLEANLINESS_TRIGGERED | `cleanSelf` | 3 | — | clean_self |
| NEED_ENERGY_TRIGGERED | `restInPlace` | 0 | low_energy | sleep_request |
| NEED_ENERGY_OVERFLOW | `recharge` | 0 | critical | sleep_request |
| NEED_SOCIAL_TRIGGERED | `social_seek` | 4 | — | seek_social_interaction |
| NEED_SOCIAL_OVERFLOW | `social_seek` | 4 | — | seek_social_interaction |
| NEED_EXPLORATION_TRIGGERED | `exploreRoom` | 4 | — | explore_environment |

## 社交细粒度 (Social + 感知目标, 全部 Lv.4)

| Social值 | 动物目标 | 人类目标 | 无目标 |
|---------|---------|---------|-------|
| 61–70 | `testAnimalBoundary` (boundary) | `requestResourceFromHuman` (resource) | `seekHumanInteraction` (general) |
| 71–85 | `greetAnimal` (greeting) | `seekHumanInteraction` (attention) | `seekHumanInteraction` (seeking) |
| 86–100 | `inviteAnimalToPlay` (play) | `inviteHumanToPlay` (play) | `seekHumanInteraction` (seeking) |

## 语音指令 → 行为

| 指令 | Behavior | Lv | sub_priority |
|------|----------|:--:|:--:|
| CMD_BACK | `respond_owner_call` | 1 | 1 |
| CMD_COME_HERE | `respond_owner_call` | 1 | 1 |
| CMD_COMFORT | `expressJoy` | 1 | 1 |
| CMD_DEAD | `expressCalm` | 1 | 1 |
| CMD_ENCOUR | `expressJoy` | 5 | 1 |
| CMD_FIVE | `respond_touch_head` | 1 | 1 |
| CMD_FOLLOW | `respond_owner_call` | 1 | 1 |
| CMD_HAND | `respond_touch_head` | 1 | 1 |
| CMD_PRAISE | `expressJoy` | 5 | 1 |
| CMD_ROLL | `expressJoy` | 1 | 1 |
| CMD_SIT | `respond_owner_call` | 1 | 1 |
| CMD_SPIN | `expressJoy` | 1 | 1 |
| CMD_SPIT | `emergency_stop` | 0 | 1 |
| CMD_STOP | `emergency_stop` | 0 | 1 |
| EVT_VOICE_CALL_NAME | `respond_owner_call` | 1 | 1 |

---

> 从 `config/event_intent_map.yaml`、`config/emotion_behavior_map.yaml`、`config/intent_action_pool.yaml` 自动生成。
> 重新生成: `python3 /tmp/gen_table.py > docs/event_behavior_table.md`
