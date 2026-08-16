# 情绪事件映射目录

<!-- 此文件由 tools/export_emotion_event_catalog.py 自动生成，请勿手工修改。 -->

本目录的唯一数据来源是 `configs/emotions.yaml:eventRules`。基础增量会继续乘以
当前性格系数，最终情绪值限制在 `0-100`；只有下表明确列出的规则才使用元数据倍率。
同名外部事件在 `10` 秒内只计算一次，不同事件互不影响。

## 声音输入

| event_type | 固定基础情绪增量 | 元数据倍率 |
|---|---|---|
| `EVT_AUDIO_LOUD` | 恐惧（Fear）+40、焦虑（Anxiety）+20、兴奋（Excite）-10 | loudnessDb gt 80 ×1.5；loudness_db gt 80 ×1.5 |
| `EVT_AUDIO_WITH_HUMAN` | 平静（Calm）+10、愉悦（Joy）+5 | 无 |
| `EVT_VOICE_PRAISE` | 愉悦（Joy）+30、兴奋（Excite）+20、平静（Calm）+5 | masterId truthy ×1.2；master_id truthy ×1.2；speakerIsMaster truthy ×1.2 |
| `EVT_VOICE_SCOLD` | 焦虑（Anxiety）+25、恐惧（Fear）+15、愉悦（Joy）-10 | 无 |
| `EVT_VOICE_COMFORT` | 焦虑（Anxiety）-25、恐惧（Fear）-15、平静（Calm）+20 | 无 |
| `EVT_VOICE_COMMAND_KNOWN` | 好奇（Curious）+15、平静（Calm）+10 | 无 |
| `EVT_VOICE_COMMAND_UNKNOWN` | 焦虑（Anxiety）+15、好奇（Curious）+10 | 无 |
| `EVT_VOICE_HAPPY` | 愉悦（Joy）+25、兴奋（Excite）+15、平静（Calm）+5 | 无 |
| `EVT_VOICE_SAD` | 焦虑（Anxiety）+15、平静（Calm）-5 | 无 |
| `EVT_VOICE_NEUTRAL` | 平静（Calm）+5、好奇（Curious）+5 | 无 |
| `EVT_VOICE_CALL_NAME` | 愉悦（Joy）+20、兴奋（Excite）+10 | 无 |
| `EVT_VOICE_PLAY_INTERACTION` | 兴奋（Excite）+15、愉悦（Joy）+10 | 无 |
| `EVT_VOICE_STATUS_CARE` | 愉悦（Joy）+5、平静（Calm）+10 | 无 |
| `EVT_VOICE_POSITIVE_EMOTION` | 愉悦（Joy）+15、兴奋（Excite）+5 | 无 |
| `EVT_VOICE_NEGATIVE_EMOTION` | 平静（Calm）+15、好奇（Curious）+5、兴奋（Excite）-15、愉悦（Joy）-5 | 无 |
| `EVT_VOICE_MASTER_ID` | 平静（Calm）+15 | 无 |
| `EVT_VOICE_STRANGER_ID` | 恐惧（Fear）+15、好奇（Curious）+10 | 无 |

## 触摸输入

| event_type | 固定基础情绪增量 | 元数据倍率 |
|---|---|---|
| `EVT_TACTILE_HEAD_PET` | 愉悦（Joy）+25、平静（Calm）+15、兴奋（Excite）+5 | 无 |
| `EVT_TACTILE_NOSE_TOUCH` | 好奇（Curious）+10、平静（Calm）+5 | 无 |
| `EVT_TACTILE_EAR_TOUCH` | 愉悦（Joy）+20、平静（Calm）+10 | 无 |
| `EVT_TACTILE_CHIN_RUB` | 愉悦（Joy）+30、平静（Calm）+10、兴奋（Excite）+5 | 无 |
| `EVT_TACTILE_FACE_TOUCH` | 愉悦（Joy）+15、焦虑（Anxiety）+10 | 无 |
| `EVT_TACTILE_MUZZLE_GRAB` | 恐惧（Fear）+35、焦虑（Anxiety）+20 | 无 |
| `EVT_TACTILE_PUT_IN_MOUTH` | 恐惧（Fear）+40、焦虑（Anxiety）+15 | 无 |
| `EVT_TACTILE_BODY_STROKE` | 愉悦（Joy）+20、平静（Calm）+15 | 无 |
| `EVT_TACTILE_BELLY_TRUST` | 愉悦（Joy）+35、平静（Calm）+15 | 无 |
| `EVT_TACTILE_BELLY_TENSE` | 恐惧（Fear）+20、焦虑（Anxiety）+15 | 无 |
| `EVT_TACTILE_PAW_HOLD` | 好奇（Curious）+10、平静（Calm）+5 | 无 |
| `EVT_TACTILE_PAW_PAD_SLEEP` | 平静（Calm）+10 | 无 |
| `EVT_TACTILE_PAW_PAD_WAKE` | 恐惧（Fear）+25、焦虑（Anxiety）+15 | 无 |
| `EVT_TACTILE_HIP_ACCEPT` | 愉悦（Joy）+15 | 无 |
| `EVT_TACTILE_HIP_RESIST` | 恐惧（Fear）+20、焦虑（Anxiety）+15 | 无 |
| `EVT_TACTILE_TAIL_GRAB` | 恐惧（Fear）+30、焦虑（Anxiety）+20 | 无 |

## 视觉输入

| event_type | 固定基础情绪增量 | 元数据倍率 |
|---|---|---|
| `EVT_VISION_MASTER_HAPPY` | 愉悦（Joy）+30、兴奋（Excite）+15、平静（Calm）+5 | 无 |
| `EVT_VISION_MASTER_SAD` | 焦虑（Anxiety）+15、平静（Calm）-5 | 无 |
| `EVT_VISION_MASTER_NEUTRAL` | 平静（Calm）+5、好奇（Curious）+5 | 无 |
| `EVT_VISION_MASTER` | 愉悦（Joy）+25、兴奋（Excite）+15、平静（Calm）+10 | 无 |
| `EVT_VISION_STRANGER` | 恐惧（Fear）+15、好奇（Curious）+20 | 无 |
| `EVT_VISION_STRANGER_ALERT` | 恐惧（Fear）+15、好奇（Curious）+20 | 无 |
| `EVT_VISION_STRANGER_FRIEND` | 兴奋（Excite）+10、好奇（Curious）+20 | 无 |
| `EVT_VISION_FOOD` | 兴奋（Excite）+35、愉悦（Joy）+20、好奇（Curious）+10 | 无 |
| `EVT_VISION_TOY` | 兴奋（Excite）+30、好奇（Curious）+20、愉悦（Joy）+15 | 无 |
| `EVT_VISION_FALL` | 焦虑（Anxiety）+20、好奇（Curious）+10 | 无 |
| `EVT_VISION_STOP_GESTURE` | 平静（Calm）+10、好奇（Curious）+15 | 无 |
| `EVT_VISION_HAND_TO_NOSE` | 好奇（Curious）+15、平静（Calm）+5 | 无 |
| `EVT_VISION_HAND_TO_NOSE_FEAR` | 恐惧（Fear）+15、焦虑（Anxiety）+10 | 无 |
| `EVT_VISION_ANIMAL_CALM` | 平静（Calm）+10、好奇（Curious）+5 | 无 |
| `EVT_VISION_ANIMAL_GREET` | 兴奋（Excite）+15、愉悦（Joy）+10 | 无 |
| `EVT_VISION_ANIMAL_PLAY` | 兴奋（Excite）+30、愉悦（Joy）+20 | 无 |
| `EVT_VISION_ANIMAL_BOUNDARY` | 恐惧（Fear）+10、好奇（Curious）+15 | 无 |
