# Marsdog 需求与情绪计算 API

当前仓库提供内部需求计算、情绪计算、ROS2 输入适配和状态/事件发布接口。

完整 ROS2 Topic 输入输出格式见 [ros2_topic_contract.md](ros2_topic_contract.md)。
行为模块升级步骤见
[内部需求 V2 联调迁移说明](2026-07-29_internal_need_v2_integration_guide.md)。

## 核心入口

```python
from marsdog_core import (
    MarsdogEmotionSystem,
    MarsdogNeedSystem,
    MarsdogPersonalitySystem,
    MarsdogTimeController,
    VirtualTickScheduler,
)

needSystem = MarsdogNeedSystem()
emotionSystem = MarsdogEmotionSystem()
personalitySystem = MarsdogPersonalitySystem()
```

## 时间测试接口

- `GetTimeScaleValue()`：读取当前 `1-100` 整数倍率。
- `GetTimeRevisionValue()`：读取运行时倍率配置修订号。
- `GetVirtualStartDateTimeValue()`：读取本次进程虚拟起点。
- `GetVirtualDateTimeValue()`：按单调时钟读取当前虚拟日期时间。
- `GetVirtualTimestampValue()`：读取当前虚拟 Unix 时间戳。
- `GetRealIntervalValue(virtualSeconds)`：把虚拟间隔换算成真实定时器周期。
- `GetTimeContextValue()`：生成输出消息使用的虚拟时间上下文。
- `SetTimeScaleValue(timeScale)`：连续切换到 `1-100` 整数倍率，不重置当前虚拟时间。
- `SetTimeContextValue(timeContext)`：使用权威时间 Topic 的 `scale` 同步本地时钟；
  `mode` 仅为兼容显示字段，不参与校验或计算。
- `VirtualTickScheduler.GetDueTickDateTimesValue(currentDateTime)`：按顺序读取并消费所有遗漏 Tick。

## 需求接口

- `GetDemandValue(demandType)`：读取 `Hunger / Bladder / Sleepiness / Cleanliness / Energy / Social / Exploration`。
- `SetDemandValue(demandType, value)`：写入需求值，自动限制在 `0-100`。
- `GetAllDemands()`：返回所有需求值。
- `IsDemandUrgent(demandType)`：按 `configs/demands.yaml` 判断是否超过触发阈值。
- `GetMostUrgentDemand()`：返回已触发需求中原始值最高的需求名。
- `GetAllDemandSignals()`：返回所有已触发的需求信号。
- `GetDemandLevelValue(demandType, value=None)`：读取指定需求当前等级，返回
  `NORMAL / TRIGGERED / URGENT / OVERFLOW`；未配置的等级会跳过。
- `GetAllDemandLevels()`：读取全部需求等级。
- `GetDemandLevelEventsValue()`：读取全部需求当前等级对应的事件名映射。
- `GetDemandSignalSnapshotValue()`：读取当前需求等级快照。
- `GetDemandSignalEventsValue(timestamp=None)`：获取需求等级变化事件；调用后会刷新快照。
- `GetInternalNeedStateValue(timestamp=None)`：返回可发布到 `/internal_need/state` 的完整状态。

需求 V2 阈值如下，比较符均为严格大于：

| 需求 | 首次触发 | 中间紧急 | 满溢 |
|---|---:|---:|---:|
| `Hunger` | `>70` | 无 | `>90` |
| `Bladder` | `>75` | 无 | 无 |
| `Sleepiness` | `>65` | 无 | `>90` |
| `Cleanliness` | `>70` | 无 | 无 |
| `Energy` | `>80` | 无 | `>90` |
| `Social` | `>60` | `>70` | `>85` |
| `Exploration` | `>60` | 无 | 无 |

## 全局需求生命周期接口

- `IsDemandLocked(currentTime=None)`：判断当前是否处于 `00:00-06:00` 普通需求锁定时段。
- `UpdateNaturalDemandsByTime(currentTime=None)`：每 10 分钟调用一次，统一更新自然需求。
- `ResetDemandsToMorningInitialValues(currentTime=None)`：恢复晨起需求值，但不重置持续耗电的 Energy。
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

- `InitializeStartupEnergy()`：每次进程启动时初始化满电，`Energy = 0`。
- `InitializeMorningEnergy()`：兼容旧调用；显式调用时同样重新初始化为满电。
- `GetBatteryValue()`：读取当前电量，返回 `100 - Energy`。
- `SetEnergyBatteryValue(value)`：写入当前电量，并保存 `Energy = 100 - value`。
- `UpdateEnergyByTime(currentTime=None, elapsedSeconds=None)`：按指定的电池计时秒数结算自然耗电；普通 Tick 默认计入 600 秒。
- `ExecuteRecharge()`：充电到配置的目标电量，并降低对应 Energy 需求。
- `Recharge()`：APP 充电接口。

Energy 在凌晨需求锁定和睡眠期间仍持续衰减，并由需求 Tick 补算。普通时段
跟随虚拟倍率，两小时续航在 `time_scale=S` 时对应 `7200/S` 秒真实时间，
例如 24 倍为 300 秒、100 倍为 72 秒。启用凌晨特殊加速时例外：
`00:00-06:00` 只按加速窗口实际经过时间以 1 倍耗电，默认整个窗口只计
30 秒，而不是计入 6 个虚拟小时。

## 社交接口

- `InitializeMorningSocial()`：晨起 `Social = random(20,30) * k_social`。
- `UpdateSocialByTime(currentTime=None)`：白天/傍晚按 Tick 增长。
- `OnOwnerPresenceChanged(isPresent)`：处理主人在家/离家状态。
- `GetSocialOutcomeRecoveryValue(socialOutcome)`：读取社交结果对应的 Social 恢复值。

## 探索接口

- `InitializeMorningExploration()`：晨起 `Exploration = random(10,20) * k_curious`。
- `UpdateExplorationByTime(currentTime=None)`：白天且 `Energy < 50`（电量 `>50%`）时每 Tick `+5`。
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
- `ApplyEmotionDecay(elapsedSeconds=1.0)`：按真实经过秒数衰减
  `Joy / Excite / Fear / Curious`；`Anxiety / Calm` 不自然衰减。ROS2 节点
  固定按真实时间驱动，不受 `time_scale` 影响。
- `IsEmotionTriggered(emotionType, value=None)`：判断普通情绪是否达到单一触发
  阈值；Calm 返回当前兜底平静状态。
- `IsCalmFallbackActive()`：判断 Joy、Excite、Anxiety、Fear、Curious 是否均未
  触发。
- `GetAllEmotionSignals()`：返回当前全部已触发情绪。
- `GetEmotionSignalSnapshotValue()`：返回全部情绪的触发布尔快照。
- `GetEmotionSignalEventsValue(timestamp=None)`：普通情绪返回未触发到已触发的
  上升沿事件；无其他触发情绪时每次检查都返回 Calm 事件。
- `GetEmotionStateValue(timestamp=None)`：返回可发布到 `/emotion/state` 的完整状态。
- `OnEmotionChanged(callback)`：注册情绪变化回调。
- `ApplyActionResultEmotion(resultType)`：按行为结果映射更新情绪。
- `OnBehaviorResultEvent(resultData)`：消费 `/behavior/result_event` 并更新情绪。
- `OnTactileEvent(metadata)`：消费单个触觉 `event_type` 并应用已有情绪映射。

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
- `/perception/tactile_event`：`std_msgs/String` JSON，需求节点和情绪节点都订阅；
  ONE1000 适配节点在有效摸头上升沿发布 `EVT_TACTILE_HEAD_PET`。
- `/behavior/result_event`：`std_msgs/String` JSON，需求节点和情绪节点都订阅。
- `/personality/state`：`std_msgs/String` JSON，需求节点和情绪节点都订阅，用于同步性格参数。
- `/simulation/time_state`：`std_msgs/String` JSON，需求和情绪节点订阅的权威虚拟时间 Tick。

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
- `/emotion/state`：情绪状态，每个虚拟秒发布。
- `/emotion/signal_event`：普通情绪从未触发变为已触发时发布；没有其他触发
  情绪时以真实时间 1 Hz 持续发布 Calm，且不受 `time_scale` 影响。
- `/personality/state`：性格状态，`personality_node` 启动时和性格变化后发布。
- `/simulation/time_state`：统一时间节点发布初始化、逐秒 Tick 和倍率变化。
- `/simulation/midnight_test_result`：凌晨场景测试完成结果，仅测试 launch 发布。
- `/perception/tactile_event`：`one1000_tactile_node` 的摸头离散事件输出，
  `RELIABLE, depth=10`。
- `/one1000/status`：`one1000_tactile_node` 以真实时间 1 Hz 发布硬件诊断状态，
  包含连接、心跳、雷达状态和最近的原始摸头位，`RELIABLE, depth=10`。

需求和情绪 Topic 均使用 `schema_version=2.0`。需求 V2 支持可选的
`URGENT` 中间等级；情绪 V2 不包含等级、区间或主导情绪事件字段。

## ROS2 参数接口

性格参数由 `personality_node` 统一维护。修改入口使用 ROS2 参数服务，状态通过 `/personality/state` 发布。

启动四个节点：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py
```

设置初始时间参数：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=12 virtual_start_time:=06:00 random_seed:=12345
```

- `time_scale`：`1-100` 整数，可在统一时间节点运行时修改。
- `virtual_start_time`：`auto` 或严格 `HH:MM`。
- `random_seed`：`-1` 或非负整数。
- `midnight_acceleration_enabled`：只读 bool；任意 `time_scale=1-100` 均可启用，
  每天虚拟 `00:00-06:00` 使用离散加速。
- `midnight_duration_seconds`：只读正数；凌晨六小时使用的真实秒数，默认30。
- `one1000_tactile_enabled`：联调 launch 是否启动 ONE1000 触摸节点，默认 `false`。
- `one1000_serial_port`：ONE1000 串口设备，默认 `/dev/ttyUSB1`。
- `one1000_auto_start_sentry`：是否自动设置阈值、清缓存并启动哨兵，默认 `true`。
- `one1000_touch_threshold`：厂商摸头灵敏度阈值，`1-65535`，默认30。
- `one1000_touch_cooldown_seconds`：两次摸头事件的真实时间冷却，默认1秒。

运行中修改倍率：

```bash
ros2 param set /time_controller_node time_scale 100
```

不要修改 `internal_need_node` 或 `emotion_engine_node` 的 `time_scale` 参数；它们运行时
以 `/simulation/time_state` 为准。`virtual_start_time` 和 `random_seed` 仍需重启
后修改。

从00:00连续运行，凌晨30秒加速，06:00后恢复所选基础倍率且不退出：

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

该模式支持任意 `1-100` 基础倍率并每天重复：`00:00-06:00` 使用30秒，
其他时段恢复 `time_scale`。同事的行为模块仍需在收到睡眠需求后回传
`ACTION_SLEEP + STARTED`。

只独立验收凌晨流程并在06:00自动退出：

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 random_seed:=12345
```

该 launch 不启动生产时间控制节点，而由 `midnight_test_node` 发布36个虚拟
10分钟测试步骤，并在首次困倦触发后自动发布 `ACTION_SLEEP + STARTED`。
到达虚拟 `06:00` 后等待最终需求状态，输出 `PASSED/FAILED` 并自动退出。

只调试性格节点：

```bash
ros2 run marsdog_need_emotion personality_node
```

只调试 ONE1000 摸头输入：

```bash
ros2 launch marsdog_need_emotion one1000_tactile.launch.py \
  serial_port:=/dev/ttyUSB1 touch_threshold:=30
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
