# Marsdog 需求与情绪计算 API

当前仓库提供内部需求计算、情绪计算、ROS2 输入适配和状态/事件发布接口。

完整 ROS2 Topic 输入输出格式见 [ros2_topic_contract.md](ros2_topic_contract.md)。

## 核心入口

```python
from marsdog_core import MarsdogNeedSystem, MarsdogEmotionSystem, MarsdogPersonalitySystem

needSystem = MarsdogNeedSystem()
emotionSystem = MarsdogEmotionSystem()
personalitySystem = MarsdogPersonalitySystem()
```

## 需求接口

- `GetDemandValue(demandType)`：读取 `Hunger / Bladder / Sleepiness / Cleanliness / Energy / Social / Exploration`。
- `SetDemandValue(demandType, value)`：写入需求值，自动限制在 `0-100`。
- `GetAllDemands()`：返回所有需求值。
- `IsDemandUrgent(demandType)`：按 `configs/demands.yaml` 判断是否超过触发阈值。
- `GetMostUrgentDemand()`：返回已触发需求中原始值最高的需求名。
- `GetAllDemandSignals()`：返回所有已触发的需求信号。
- `GetDemandLevelValue(demandType, value=None)`：读取指定需求当前等级，返回 `NORMAL / TRIGGERED / OVERFLOW`。
- `GetAllDemandLevels()`：读取全部需求等级。
- `GetDemandLevelEventsValue()`：读取全部需求当前等级对应的事件名映射。
- `GetDemandSignalSnapshotValue()`：读取当前需求等级快照。
- `GetDemandSignalEventsValue(timestamp=None)`：获取需求等级变化事件；调用后会刷新快照。
- `GetInternalNeedStateValue(timestamp=None)`：返回可发布到 `/internal_need/state` 的完整状态。

## 全局需求生命周期接口

- `IsDemandLocked(currentTime=None)`：判断当前是否处于 `00:00-06:00` 普通需求锁定时段。
- `UpdateNaturalDemandsByTime(currentTime=None)`：每 10 分钟调用一次，统一更新自然需求。
- `ResetDemandsToMorningInitialValues(currentTime=None)`：恢复所有需求晨起值。
- `ApplyInterruptedDemandDelta(demandType)`：内部需求行为被打断时扣减对应需求。
- `GetDemandTypeByAction(actionType)`：根据 `ACTION_*` 查对应需求类型，用于行为结果结算。
- `OnBehaviorResultEvent(resultData)`：消费 `/behavior/result_event` 并更新需求。

## 饥渴接口

- `InitializeMorningHunger()`：晨起 `Hunger` 随机到 `60-70`。
- `UpdateHungerByTime(currentTime=None)`：白天每 Tick `Hunger += 1`。
- `GetHungerRecoveryValue(foodType, portions, eatEfficiency)`：计算进食恢复值。
- `ExecuteEat(foodType="NormalFood", portions=1, eatEfficiency="Full")`：按进食结果更新需求。
- `Feed(...)`：APP 喂食接口，内部调用 `ExecuteEat()`。

## 排泄接口

- `InitializeMorningBladder()`：晨起 `Bladder` 随机到 `20-30`。
- `UpdateBladderByTime(currentTime=None)`：白天每 Tick `Bladder += 3`。
- `ApplyBladderAfterEat(hungerBeforeEat)`：进食后按进食前 `Hunger` 增加排泄值。
- `ApplyBladderEventBonus(eventType)`：关键事件排泄加成。
- `ExecuteDefecate()`：排泄成功后 `Bladder = 0`。
- `Defecate()`：APP 排泄接口。

## 困倦接口

- `InitializeMorningSleepiness()`：晨起 `Sleepiness` 随机到 `10-15`。
- `UpdateSleepinessByTime(currentTime=None)`：按白天、夜晚、凌晨、关灯规则更新。
- `UpdateSleepTriggerState(currentTime=None)`：刷新是否允许进入睡眠。
- `IsSleepActionAllowed(currentTime=None)`：判断是否满足睡眠触发条件。
- `SetLightsOffValue(isLightsOff)`：设置关灯状态。
- `IsSleeping()`：读取当前是否睡眠中。
- `GetSleepDepthValue()`：读取 `Shallow / Deep`。
- `ExecuteSleep()`：进入浅睡状态。
- `ApplySleepRecovery(currentTime=None)`：执行一次睡眠恢复 Tick。
- `WakeUp(currentTime=None)`：结束睡眠状态。

## 清洁接口

- `InitializeMorningCleanliness()`：晨起 `Cleanliness` 随机到 `5-15`。
- `UpdateCleanlinessByTime(currentTime=None)`：白天每 Tick `Cleanliness += 2`。
- `ApplyCleanlinessAfterEat()`：进食后 `Cleanliness += 20`。
- `ExecuteGroom()`：清洁完成后 `Cleanliness -= 50`。
- `Groom()`：APP 清洁接口。

## 精力接口

- `InitializeMorningEnergy()`：晨起 `Energy = 100`。
- `GetBatteryValue()`：读取当前电量，也就是 `Energy`。
- `SetEnergyBatteryValue(value)`：写入当前电量。
- `ExecuteRecharge()`：充电完成后恢复到配置目标。
- `Recharge()`：APP 充电接口。

## 社交接口

- `InitializeMorningSocial()`：晨起 `Social = random(20,30) * k_social`。
- `UpdateSocialByTime(currentTime=None)`：白天/傍晚按 Tick 增长。
- `OnOwnerPresenceChanged(isPresent)`：处理主人在家/离家状态。
- `GetSocialOutcomeRecoveryValue(socialOutcome)`：读取社交结果对应的 Social 恢复值。

## 探索接口

- `InitializeMorningExploration()`：晨起 `Exploration = random(10,20) * k_curious`。
- `UpdateExplorationByTime(currentTime=None)`：白天且 `Energy > 50` 时每 Tick `+5`。
- `ExecuteExploration(resultType=None)`：探索完成后统一按 `Completed` 结算，`resultType` 仅保留兼容。

## 情绪接口

- `GetEmotionValue(emotionType)`：读取 `Joy / Excite / Anxiety / Fear / Curious / Calm`。
- `SetEmotionValue(emotionType, value)`：写入情绪值，自动限制在 `0-100`。
- `GetAllEmotions()`：返回所有情绪值。
- `GetDominantEmotion()`：返回当前值最高的情绪。
- `ApplyEmotionDelta(emotionType, delta)`：按增量修改情绪。
- `ApplyEmotionEvent(eventName, metadata=None)`：按 `configs/emotions.yaml:eventRules` 应用外部事件。
- `GetEmotionEventMappingValue(eventName)`：读取指定事件映射。
- `GetLastEmotionEventResultValue()`：读取最近一次情绪事件计算结果。
- `ApplyEmotionDecay(elapsedSeconds=1.0)`：按自然平复公式衰减情绪。
- `GetEmotionLevelValue(emotionType, value=None)`：读取指定情绪所在区间。
- `GetAllEmotionLevels()`：读取全部情绪区间。
- `GetEmotionLevelEventsValue()`：读取全部情绪当前区间对应的事件名映射。
- `GetDominantEmotionSignalValue()`：读取主导情绪及其区间事件。
- `GetEmotionSignalEventsValue(timestamp=None)`：获取区间变化事件；调用后会刷新快照。
- `GetEmotionStateValue(timestamp=None)`：返回可发布到 `/emotion/state` 的完整状态。
- `OnEmotionChanged(callback)`：注册情绪变化回调。
- `ApplyActionResultEmotion(resultType)`：按行为结果映射更新情绪。
- `OnBehaviorResultEvent(resultData)`：消费 `/behavior/result_event` 并更新情绪。

## 性格接口

- `SetPersonalityProfileValue(profileName)`：应用性格预设。
- `SetPersonalityParamValue(paramName, value)`：设置单个 `A/O/E/C`，成功后性格预设切换为 `Custom`。
- `SetPersonalityParamsValue(params)`：设置完整 `A/O/E/C`，成功后性格预设切换为 `Custom`。
- `SetPersonalityStateValue(stateData)`：从 `/personality/state` 风格字典同步性格状态。
- `GetPersonalityProfileValue()`：读取当前性格预设。
- `GetAllPersonalityParams()`：读取全部 `A/O/E/C`。
- `GetPersonalityStateValue(timestamp=None)`：返回可发布到 `/personality/state` 的完整状态。
- `GetSocialPersonalityCoefficientValue()`：读取 `Social` 晨起系数。
- `GetEmotionPersonalityCoefficientValue(emotionType)`：读取指定情绪性格系数。

`coefficients` 是只读派生值，由 `A/O/E/C` 自动计算，外部不应直接设置。

## ROS2 Topic

### 输入

- `/perception/audio_event`：`std_msgs/String` JSON，需求节点和情绪节点都订阅。
- `/perception/visual_event`：`std_msgs/String` JSON，需求节点和情绪节点都订阅。
- `/behavior/result_event`：`std_msgs/String` JSON，需求节点和情绪节点都订阅。
- `/personality/state`：`std_msgs/String` JSON，需求节点和情绪节点都订阅，用于同步性格参数。

`/behavior/result_event` 的 `data` 必须是 JSON 对象：

```json
{
  "event_id": "result-000001",
  "timestamp": 1710000000.0,
  "action_type": "ACTION_EAT",
  "demand_type": "Hunger",
  "result_type": "COMPLETED",
  "metadata": {
    "foodType": "NormalFood",
    "portions": 1,
    "eatEfficiency": "Full"
  }
}
```

字段要求：

- `event_id`：建议填写；重复 `event_id` 只处理一次。
- `action_type`：必填，必须能映射到内部需求。
- `demand_type`：建议填写；填写时必须与 `action_type` 映射一致。
- `result_type`：必填，只接受 `STARTED / COMPLETED / FAILED / INTERRUPTED / CANCELLED / TIMEOUT`。
- `metadata`：必填 JSON 对象；无额外字段时传 `{}`。

当前接受 `ACTION_EAT / ACTION_DEFECATE / ACTION_SLEEP / ACTION_GROOM /
ACTION_RECHARGE / ACTION_PLAY_INVITE / ACTION_SOCIAL_GREET /
ACTION_BOUNDARY_TEST / ACTION_ATTENTION_SEEK / ACTION_RESOURCE_SHARE /
ACTION_EXPLORE / ACTION_SPACE_EXPLORE / ACTION_OBJECT_EXPLORE`。其他 action
会被忽略。

### 输出

- `/internal_need/state`：内部需求状态，1 秒持续发布。
- `/internal_need/signal_event`：内部需求等级变化事件，等级变化时发布。
- `/emotion/state`：情绪状态，1 秒持续发布。
- `/emotion/signal_event`：情绪区间或主导情绪变化时发布。
- `/personality/state`：性格状态，`personality_node` 启动时和性格变化后发布。

`/internal_need/state.levelEvents[demand]` 和 `/emotion/state.levelEvents[emotion]`
与对应 signal 事件的 `event_type` 使用同一套事件名，可用于跨话题对比。

## ROS2 参数接口

性格参数由 `personality_node` 统一维护。修改入口使用 ROS2 参数服务，状态通过 `/personality/state` 发布。

启动三个节点：

```bash
ros2 launch marsdog_behavior internal_need_emotion.launch.py
```

只调试性格节点：

```bash
ros2 run marsdog_behavior personality_node
```

设置预设：

```bash
ros2 param set /personality_node profile SunnyExplorer
```

设置自定义 `A/O/E/C`：

```bash
ros2 param set /personality_node A 85
ros2 param set /personality_node O 75
ros2 param set /personality_node E 30
ros2 param set /personality_node C 40
```

查看状态：

```bash
ros2 topic echo /personality/state --field data
```
