# Marsdog Core API

## 需求接口

- `GetDemandValue(demandType)`：读取 `Hunger`、`Bladder`、`Sleepiness`、`Cleanliness`、`Energy`、`Social`、`Exploration`。
- `SetDemandValue(demandType, value)`：写入需求值，自动限制在 `0-100`。
- `GetAllDemands()`：返回所有需求值。
- `IsDemandUrgent(demandType)`：按 `configs/demands.yaml` 判断是否触发。
- `GetMostUrgentDemand()`：返回已触发需求中原始值最高的需求名。

## 情绪接口

- `GetEmotionValue(emotionType)`：读取 `Joy`、`Excite`、`Anxiety`、`Fear`、`Curious`、`Calm`。
- `SetEmotionValue(emotionType, value)`：写入情绪值，自动限制在 `0-100`。
- `ApplyEmotionDelta(emotionType, delta)`：增量修改情绪值。
- `OnEmotionChanged(callback)`：注册情绪变化回调，回调参数为 `(emotionName, oldValue, newValue)`。
- `ApplyActionResultEmotion(resultType)`：按行为执行结果更新情绪，支持 `DemandSatisfied`、`DemandUnsatisfied`、`ActionInterrupted`。

## 行为引擎接口

- `Tick(currentTime=None, applyDemandGrowth=True)`：执行一帧行为仲裁；仿真中默认同时执行一次 10 分钟需求增长。
- `GetCurrentAction()`：返回当前顶层行为，如 `ACTION_EAT`。
- `GetActionQueue()`：返回当前唯一顶层行为队列。
- `GetConcreteActionQueue()`：返回当前顶层行为展开后的 `ACT_*` 具体动作序列。
- `GetActionSequence(actionType)`：读取指定顶层行为对应的具体动作序列库。
- `GetCurrentActionSequence()`：读取当前行为对应的具体动作序列库。
- `TickCurrentBehaviorTree()`：执行当前顶层行为内部行为树，返回 `RUNNING / SUCCESS / FAILURE`。
- `GetCurrentConcreteAction()`：获取当前行为树正在执行的 `ACT_*` 动作。
- `MarkCurrentConcreteActionDone()`：由执行层标记当前 `ACT_*` 动作完成。
- `IsCurrentBehaviorTreeFinished()`：判断当前行为树是否结束。
- `SetPriorityMode(mode)`：设置 `Normal`、`Emergency`、`Idle`，第一版只保存模式，不改变仲裁规则。

## 全局需求规则接口

- `IsDemandLocked(currentTime=None)`：判断当前是否处于凌晨需求自然计算锁定时段。
- `UpdateNaturalDemandsByTime(currentTime=None)`：按全局规则更新自然需求；`00:00-06:00` 不计算，离开锁定期后执行晨起重置。
- `ResetDemandsToMorningInitialValues(currentTime=None)`：把所有需求恢复到晨起初始值。
- `ApplyInterruptedDemandDelta(demandType)`：内部需求被打断时，对该需求统一施加 `-20`。
- `ExecuteDemandInterrupted(demandType)`：执行“需求 -20 + 行为情绪映射表”的完整中断结果。

## 饥渴行为接口

- `InitializeMorningHunger()`：晨起时把 `Hunger` 随机初始化到 `60-70`。
- `UpdateHungerByTime(currentTime=None)`：每 10 分钟调用一次；若处于全局需求锁定时段则不计算，白天 `06:00-21:00` 执行 `Hunger += 1`，其他时间不增加。
- `GetHungerRecoveryValue(foodType, portions, eatEfficiency)`：计算恢复值，公式为 `单份恢复力 * 进食效率 * 食物份数`。
- `ExecuteEat(foodType="NormalFood", portions=1, eatEfficiency="Full")`：执行进食并降低 `Hunger`。
- `Feed(foodType="NormalFood", portions=1, eatEfficiency="Full")`：APP 喂食接口，内部调用 `ExecuteEat()`。

## 排泄行为接口

- `InitializeMorningBladder()`：晨起时把 `Bladder` 随机初始化到 `20-30`。
- `UpdateBladderByTime(currentTime=None)`：每 10 分钟调用一次；白天 `06:00-21:00` 执行 `Bladder += 3`，其他时间不增加。
- `ApplyBladderAfterEat(hungerBeforeEat)`：进食完成后根据进食前 `Hunger` 增加 `Bladder`，`Hunger > 90` 增加 `25`，`Hunger > 70` 增加 `20`。
- `ApplyBladderEventBonus(eventType)`：预留关键事件加成，当前支持 `AfterDrink` 和 `AfterPlay`。
- `ExecuteDefecate()`：排泄成功后将 `Bladder` 设置为 `0`。
- `Defecate()`：APP 排泄接口，内部调用 `ExecuteDefecate()`。

## 清洁行为接口

- `InitializeMorningCleanliness()`：晨起时把 `Cleanliness` 随机初始化到 `5-15`。
- `UpdateCleanlinessByTime(currentTime=None)`：每 10 分钟调用一次；白天 `06:00-21:00` 执行 `Cleanliness += 2`，其他时间不增加。
- `ApplyCleanlinessAfterEat()`：进食完成后让 `Cleanliness += 20`。
- `ExecuteGroom()`：执行清洁行为并让 `Cleanliness -= 50`。
- `Groom()`：APP 清洁接口，内部调用 `ExecuteGroom()`。

## 精力/电量行为接口

- `InitializeMorningEnergy()`：晨起时把 `Energy` 初始化为 `100`。
- `GetBatteryValue()`：读取当前硬件电量百分比，也就是 `Energy`。
- `SetEnergyBatteryValue(value)`：写入当前硬件电量百分比，自动限制在 `0-100`。
- `ExecuteRecharge()`：执行恢复精力行为并将 `Energy` 恢复到配置目标值，当前为 `100`。
- `Recharge()`：APP 充电接口，内部调用 `ExecuteRecharge()`。

## 困倦行为接口

- `InitializeMorningSleepiness()`：晨起时把 `Sleepiness` 随机初始化到 `10-15`。
- `UpdateSleepinessByTime(currentTime=None)`：每 10 分钟更新一次；清醒时白天 `+3`、夜晚 `+5`，凌晨或关灯时强制到 `90`。
- `UpdateSleepTriggerState(currentTime=None)`：刷新当前 Tick 是否允许触发睡眠行为。
- `IsSleepActionAllowed(currentTime=None)`：判断是否满足睡眠触发条件；白天且非强制清醒可触发，凌晨或关灯强制触发。
- `SetLightsOffValue(isLightsOff)`：设置是否识别到关灯。
- `IsSleeping()`：读取当前是否处于睡眠状态。
- `GetSleepDepthValue()`：读取当前睡眠深度，返回 `Shallow` 或 `Deep`。
- `ExecuteSleep()`：行为树完成后进入浅睡状态，浅睡固定持续 3 个 Tick。
- `ApplySleepRecovery(currentTime=None)`：浅睡每 Tick `-2`；浅睡结束仍大于 `65` 则转深睡，否则醒来；深睡每 Tick `-15`，低于 `20` 醒来，凌晨 `00:00-06:00` 不醒来。
- `WakeUp()`：结束睡眠状态。
