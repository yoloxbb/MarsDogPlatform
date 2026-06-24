# Marsdog 当前实现总结

本文档总结当前仓库已经实现的行为系统能力、运行流程、ROS2 适配方式，以及每个需求状态量的实际逻辑。它描述的是当前代码状态，不是最终设计目标。

## 1. 当前整体结构

项目分为两层：

- `marsdog_core/`：纯 Python 核心行为系统，不依赖 ROS2。
- `marsdog_ros2/`：ROS2 适配层，把感知理解层消息转换成核心事件，再发布行为指令。

核心入口是 `MarsdogBehaviorSystem`，由多个 API 混入类组合而成：

- `DemandAPI`：需求读写、紧急判断、最紧急需求查询。
- `EmotionAPI`：情绪读写、情绪增量、行为结果情绪映射。
- `EventAPI`：外部事件队列和事件回调。
- `SensorInputAPI`：声音、视觉、触觉、环境输入转换。
- `DemandLifecycleAPI`：全局时间增长、凌晨锁定、晨起重置、中断需求衰减。
- `HungerBehaviorAPI`：饥渴行为闭环。
- `BladderBehaviorAPI`：排泄行为闭环。
- `SleepinessBehaviorAPI`：困倦/睡眠状态机。
- `CleanlinessBehaviorAPI`：清洁行为闭环。
- `EnergyBehaviorAPI`：精力/电量行为闭环。
- `SocialBehaviorAPI`：社交增长、目标选择和互动会话状态机。
- `ExplorationBehaviorAPI`：探索增长、目标新旧识别、动作上下文和结果结算。
- `PersonalityAPI`：性格预设和情绪性格系数计算。
- 动作反馈接口：当前在 `MarsdogBehaviorSystem` 中提供 `GetCurrentActionCommand()` 和 `OnActionFeedback()`。
- `DebugAPI`：系统状态、性格参数、调试开关。

## 2. Tick 主流程

每次调用 `Tick(currentTime=None, applyDemandGrowth=True)` 时，流程如下：

1. 如果 `applyDemandGrowth=True`，调用 `UpdateNaturalDemandsByTime(currentTime)` 更新自然增长需求。
2. 刷新困倦触发状态 `UpdateSleepTriggerState(currentTime)`。
3. 仲裁器 `BehaviorArbiter.DecideNextAction()` 按 `Lv.0 -> Lv.6` 顺序选择唯一顶层行为。
4. 如果新行为优先级高于当前行为，则中断当前行为树，并对被中断的内部需求执行需求衰减和情绪映射。
5. 更新 `currentAction`、`currentPriorityLevel`、`currentDemandType` 和行为队列。
6. 清空当前帧 `pendingEvents`。

当前系统每帧只输出一个顶层行为，`actionQueue` 只是当前行为的单项列表，用于避免同一行为重复排队。

## 3. 优先级仲裁

优先级配置在 `configs/priorities.yaml`。

当前层级如下：

| 层级 | 规则 | 触发条件 | 输出行为 |
|---|---|---|---|
| Lv.0 | 生存避险 | `Danger / Pain / Weightlessness` | `ACTION_FLEE` |
| Lv.0 | 低电量生命保障 | `Energy < 20` | `ACTION_RECHARGE` |
| Lv.1 | 排泄 | `Bladder > 75` | `ACTION_DEFECATE` |
| Lv.1 | 困倦 | `Sleepiness > 65` 且睡眠状态允许 | `ACTION_SLEEP` |
| Lv.2 | 人类社交事件 | `OwnerCall`，不受 Social 阈值限制 | `ACTION_SOCIAL_GREET` |
| Lv.2 | 环境变化事件 | `EnvironmentChange / NewObject / OldObject / NewSound / NewSmell` 且 `metadata.value > 40` | `ACTION_OBJECT_EXPLORE` |
| Lv.3 | 饥渴 | `Hunger > 70` | `ACTION_EAT` |
| Lv.3 | 清洁 | `Cleanliness > 70` | `ACTION_GROOM` |
| Lv.4 | 社交动机 | `Social > 60` 且没有活跃社交会话 | 根据目标随机选择社交行为 |
| Lv.4 | 探索动机 | `Exploration > 60` | `ACTION_EXPLORE` |
| Lv.5 | 愉悦表达 | `Joy >= 60` | `ACTION_WAG_TAIL` |
| Lv.5 | 兴奋表达 | `Excite >= 60` | `ACTION_ZOOM` |
| Lv.5 | 焦虑表达 | `Anxiety >= 50` | `ACTION_PACE` |
| Lv.5 | 恐惧表达 | `Fear >= 50` | `ACTION_HIDE` |
| Lv.5 | 好奇表达 | `Curious >= 60` | `ACTION_SNIFF` |
| Lv.6 | 空闲 | 无其他规则命中 | `ACTION_LOAF` |

同层级有多个候选时，仲裁器按 `score` 降序选择。需求类默认 `score = 当前需求值`，事件类默认取 `metadata.value / pressure / confidence` 中的最大值，情绪类按情绪值和性格系数计算。

## 4. 行为树和动作序列

顶层行为使用 `ACTION_*`，具体动作使用 `ACT_*`。

`ActionPlanner` 根据 `configs/actions.yaml` 把顶层行为展开为内部行为树。当前支持两类动作配置：

- 固定动作列表：按 `steps` 顺序执行。
- 随机阶段动作：按 `phaseOrder`，从每个阶段动作池中随机抽取指定数量动作。

行为树执行接口：

- `TickCurrentBehaviorTree()`：推进当前行为树。
- `GetCurrentConcreteAction()`：读取当前正在执行的 `ACT_*`。
- `MarkCurrentConcreteActionDone()`：执行层反馈当前具体动作已完成。
- `GetFinishedConcreteActions()`：读取已完成动作。

面向后续动作执行层的稳定接口：

- `GetCurrentActionCommand()`：获取当前应下发的单个具体动作命令。
- `GetActiveActionCommand()`：读取已生成但尚未收到反馈的动作命令，不推进状态。
- `OnActionFeedback(commandId, actionName, status, metadata=None)`：接收执行层反馈。

动作命令格式：

```json
{
  "commandId": "cmd-000001",
  "topAction": "ACTION_EAT",
  "concreteAction": "ACT_RUN_TO_BOWL",
  "stepIndex": 0,
  "behaviorTreeStatus": "RUNNING"
}
```

反馈状态：

- `SUCCESS`：当前 `ACT_*` 执行完成，行为树推进到下一个具体动作。
- `FAILURE`：当前 `ACT_*` 执行失败，结束当前行为树，释放当前顶层行为，等待下一轮仲裁。
- `INTERRUPTED`：当前 `ACT_*` 被外部中断，结束当前行为树，并执行内部需求被打断规则。

重复执行保护：

- 同一个顶层行为正在 `RUNNING` 时，下一次 `Tick()` 即使仍命中同一需求，也不会重新启动行为树。
- 同一个具体动作未收到反馈前，`GetCurrentActionCommand()` 会复用同一个 `commandId`。
- 如果同一个顶层行为已经 `SUCCESS / FAILURE`，但下一轮仲裁仍然命中该行为，则允许重新启动新的行为树。

当行为树返回 `SUCCESS` 后，`MarsdogBehaviorSystem` 会按顶层行为调用对应的回写函数：

- `ACTION_EAT` -> `ExecuteEat()`
- `ACTION_DEFECATE` -> `ExecuteDefecate()`
- `ACTION_SLEEP` -> `ExecuteSleep()`
- `ACTION_GROOM` -> `ExecuteGroom()`
- `ACTION_RECHARGE` -> `ExecuteRecharge()`

没有配置具体动作的顶层行为会退化为只输出顶层行为本身，例如探索和情绪表达行为当前还没有完整动作树。

## 5. 全局需求生命周期

所有需求值写入时都会限制在 `0-100`。

当前全局规则：

- `00:00-06:00` 为自然需求锁定时段，普通需求不自然增长。
- 锁定时段内，`Sleepiness` 是例外，会按睡眠规则处理。
- 离开锁定时段后会执行一次晨起重置，把需求恢复到配置中的晨起初始值或随机范围。
- 内部需求行为被更高优先级打断时，默认对关联需求执行 `-20`，并触发 `ActionInterrupted` 情绪规则。
- `Bladder` 有专属中断规则：排泄被打断时 `Bladder -= 40`。

## 6. 情绪规则

情绪配置在 `configs/emotions.yaml`。

当前情绪类型：

- `Joy`
- `Excite`
- `Anxiety`
- `Fear`
- `Curious`
- `Calm`

行为结果映射：

| 行为结果 | 情绪变化 |
|---|---|
| `DemandSatisfied` | `Joy +10~20`，`Calm +5~10`，`Anxiety -15~-5` |
| `DemandUnsatisfied` | `Anxiety +5~15` |
| `ActionInterrupted` | `Anxiety +3~5` |

所有情绪也限制在 `0-100`。`OnEmotionChanged(callback)` 可注册情绪变化回调。

## 7. 各需求当前逻辑

### 7.1 Hunger 饥渴

当前状态：已实现完整闭环。

语义：`Hunger` 表示饥渴/胃部空虚程度，数值越高越需要进食。

配置：

- 默认值：`65`
- 晨起随机值：`60-70`
- 取值范围：`0-100`
- 触发阈值：`Hunger > 70`
- 满溢阈值：`Hunger > 90`

自然增长：

- `06:00-21:00`：每 10 分钟 `Hunger += 1`
- 其他时间：`Hunger += 0`
- `00:00-06:00` 全局锁定时不自然增长

行为触发：

- `Hunger > 70` 时，Lv.3 触发 `ACTION_EAT`
- `Hunger > 90` 时，动作规划使用激动进食分支

动作树：

- 激动进食：`ACT_RUN_TO_BOWL -> ACT_FAST_LICK_AND_SWALLOW`
- 正常进食：固定 `ACT_RUN_TO_BOWL`，再从准备、进食、互动、结束四个阶段各随机抽 1 个动作

行为完成回写：

- `ExecuteEat(foodType="NormalFood", portions=1, eatEfficiency="Full")`
- 恢复公式：`恢复值 = 单份恢复力 * 进食效率 * 食物份数`
- 食物恢复力：
  - `PremiumFood = 30`
  - `NormalFood = 20`
  - `Snack = 5`
- 进食效率：
  - `Full = 1.0`
  - `HalfInterrupted = 0.5`

联动影响：

- 进食前 `Hunger > 90`：`Bladder += 25`
- 进食前 `Hunger > 70`：`Bladder += 20`
- 每次进食后：`Cleanliness += 20`

情绪：

- 行为后 `Hunger` 从超过阈值降到阈值以下，触发 `DemandSatisfied`
- 行为后仍超过阈值，触发 `DemandUnsatisfied`
- 半程被打断效率时，触发 `ActionInterrupted`

### 7.2 Bladder 排泄

当前状态：已实现完整闭环。

语义：`Bladder` 表示排泄压力，数值越高越需要排泄。

配置：

- 默认值：`0`
- 晨起随机值：`20-30`
- 触发阈值：`Bladder > 75`
- 满溢阈值：`Bladder > 90`

自然增长：

- `06:00-21:00`：每 10 分钟 `Bladder += 3`
- 其他时间：`Bladder += 0`
- `00:00-06:00` 全局锁定时不自然增长

事件/行为加成：

- 进食前 `Hunger > 90` 后完成进食：`Bladder += 25`
- 进食前 `Hunger > 70` 后完成进食：`Bladder += 20`
- 预留事件加成：
  - `AfterDrink += 20`
  - `AfterPlay += 15`

行为触发：

- `Bladder > 75` 时，Lv.1 触发 `ACTION_DEFECATE`
- Lv.1 优先于 Lv.3 的饥渴/清洁

动作树：

- 从准备、排泄中、结束三个阶段各随机抽 1 个动作
- 准备动作池包括：`ACT_SNIFF_AND_CIRCLE`、`ACT_SCRATCH_GROUND`、`ACT_SQUAT_TO_PEE`、`ACT_SQUAT_TO_POOP`
- 排泄中动作池包括：`ACT_HESITATE`、`ACT_TENSE_BODY`、`ACT_TAIL_MOVEMENT`、`ACT_SLIGHT_TREMOR`、`ACT_LOWER_HEAD_OR_TURN`
- 结束动作池包括：`ACT_STAND_UP_WITH_HIND_LEGS`、`ACT_SCRATCH_SOIL_OR_GROUND`、`ACT_SNIFF_EXCREMENT`、`ACT_WALK_AWAY_OR_SHAKE_HEAD`

行为完成回写：

- `ExecuteDefecate()`：成功后 `Bladder = 0`
- 若排泄前 `Bladder > 0`，触发 `DemandSatisfied`

中断：

- 排泄被更高优先级事件打断时，使用专属规则：`Bladder -= 40`
- 同时触发 `ActionInterrupted` 情绪映射

### 7.3 Sleepiness 困倦

当前状态：已实现状态机闭环。

语义：`Sleepiness` 表示疲劳累积程度，数值越高越需要睡眠。

配置：

- 默认值：`15`
- 晨起随机值：`10-15`
- 触发阈值：`Sleepiness > 65`
- 满溢阈值：`Sleepiness > 90`
- 醒来阈值：`Sleepiness <= 20`
- 浅睡固定 Tick 数：`3` 个 Tick，即 30 分钟

清醒时自然增长：

- `06:00-21:00`：每 10 分钟 `Sleepiness += 3`
- `21:00-00:00`：每 10 分钟 `Sleepiness += 5`
- `00:00-06:00` 或关灯：清醒时直接设置 `Sleepiness = 90`

睡眠触发限制：

- `Sleepiness > 65` 且当前为白天可入睡时段，才允许触发 `ACTION_SLEEP`
- 白天可入睡窗口：`06:00-21:00`
- 强制清醒窗口：`06:00-08:00`，该时段不触发普通睡眠
- 凌晨 `00:00-06:00` 或关灯时强制允许睡眠

行为触发：

- 满足上述条件时，Lv.1 触发 `ACTION_SLEEP`
- 仲裁器除了检查 `Sleepiness > 65`，还会检查 `sleepActionAllowed`

动作树：

- `ACTION_SLEEP` 只有一个“入睡”分支
- 每次从准备入睡、睡眠中小动作、起床动作三个阶段各随机抽 1 个动作
- 深睡不是动作树分支，而是睡眠状态机在浅睡后决定

睡眠状态机：

1. 行为树成功后调用 `ExecuteSleep()`，进入浅睡：
   - `isSleeping=True`
   - `sleepDepth=Shallow`
   - `shallowSleepTicksRemaining=3`
2. 浅睡期间每 Tick：
   - `Sleepiness -= 2`
   - `shallowSleepTicksRemaining -= 1`
3. 浅睡 3 个 Tick 结束后：
   - 如果 `Sleepiness > 65`，进入深睡
   - 如果 `Sleepiness <= 65`，自然醒来
4. 深睡期间每 Tick：
   - `Sleepiness -= 15`
   - 如果 `Sleepiness <= 20` 且不在 `00:00-06:00`，自然醒来
   - 如果在 `00:00-06:00`，即使低于醒来阈值也不自然醒来
5. 晨起重置时，如果仍在睡眠状态，会调用 `WakeUp()`

### 7.4 Cleanliness 清洁

当前状态：已实现完整闭环。

语义：当前 `Cleanliness` 表示身体脏污程度，数值越高越需要清洁。

配置：

- 默认值：`10`
- 晨起随机值：`5-15`
- 触发阈值：`Cleanliness > 70`
- 满溢阈值：`Cleanliness > 90`

自然增长：

- `06:00-21:00`：每 10 分钟 `Cleanliness += 2`
- 其他时间：`Cleanliness += 0`
- `00:00-06:00` 全局锁定时不自然增长

行为联动：

- 每次进食完成后：`Cleanliness += 20`

行为触发：

- `Cleanliness > 70` 时，Lv.3 触发 `ACTION_GROOM`
- 与 `Hunger` 同为 Lv.3，同层级按当前需求原始值高低排序

动作树：

- `ACTION_GROOM` 从处理毛发动作池中随机抽 1 个动作
- 动作池包括：`ACT_LICK_PAWS_OR_FUR`、`ACT_SCRATCH`、`ACT_SHAKE_OFF_WATER`、`ACT_STRETCH_LAZILY`、`ACT_ROLL_OVER`、`ACT_RUB_AGAINST_OBJECT`、`ACT_PANT`

行为完成回写：

- `ExecuteGroom()`：`Cleanliness -= 50`
- 如果从触发状态降到阈值以下，触发 `DemandSatisfied`
- 如果清洁后仍超过阈值，触发 `DemandUnsatisfied`

### 7.5 Energy 精力/电量

当前状态：已实现闭环，但第一版是模拟充电完成，不是真实硬件充电过程。

语义：`Energy` 当前等同硬件电量百分比，数值越低越需要充电。

配置：

- 默认值：`100`
- 晨起值：`100`
- 触发阈值：`Energy < 20`
- 严重低电量阈值：`Energy < 10`
- 充电目标：`100`

自然变化：

- 当前不做自然增长或自然衰减
- 外部应通过 `SetEnergyBatteryValue(value)` 或 `SetDemandValue("Energy", value)` 写入真实电量

行为触发：

- `Energy < 20` 时，Lv.0 触发 `ACTION_RECHARGE`
- Lv.0 高于排泄、困倦、饥渴、清洁等内部需求
- 同为 Lv.0 时，危险事件 `score=100`，低电量 `score=95`，因此危险事件会优先于充电

动作树：

- `Energy < 10`：严重低电量分支
  - `ACT_RETURN_TO_CHARGER`
  - `ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER`
- `Energy < 20`：低电量分支
  - 从 `ACT_PANT_IN_PLACE`、`ACT_RESIST_WALKING`、`ACT_SLOW_MOVEMENT` 中随机抽 1 个动作

行为完成回写：

- `ExecuteRecharge()`：当前模拟为 `Energy = 100`
- 若从低电量状态恢复到阈值以上，触发 `DemandSatisfied`

### 7.6 Social 社交

当前状态：已实现需求增长、动态行为选择、动作树、互动会话状态机和外部回应结算。

语义与配置：

- `Social` 数值越高表示社交欲望越强
- 默认值：`20`
- 晨起值：`random(20, 30) * k_social`，限制在 `0-100`
- `k_social = (A/50)*0.8 + (E/50)*0.2`
- 触发阈值：`Social > 60`
- 满溢阈值：`Social > 80`

自然增长和事件：

- `06:00-18:00`：每 10 分钟 `Social += 2`
- `18:00-21:00`：每 10 分钟 `Social += 3`
- `21:00-06:00`：不增长
- 明确收到主人离家状态时：`Social += 30`，重复离家状态不重复增加

行为触发：

- 主人主动交互为 Lv.2，固定输出 `ACTION_SOCIAL_GREET`，不受 Social 阈值限制
- 狗主动社交为 Lv.4，只有 `Social > 60` 且没有活跃会话时触发
- 同时检测到人和动物时优先选择人类
- 看到人时，从 `ACTION_ATTENTION_SEEK / ACTION_PLAY_INVITE / ACTION_RESOURCE_SHARE` 中等概率随机
- 只看到动物时，从 `ACTION_SOCIAL_GREET / ACTION_PLAY_INVITE / ACTION_BOUNDARY_TEST` 中等概率随机
- 没有目标时输出 `ACTION_ATTENTION_SEEK`，固定先执行 `ACT_SEARCH_FOR_PERSON`

互动会话状态：

```text
Idle -> ExecutingAction -> WaitingResponse -> Completed/TimedOut
                       \-> Interrupted/Failed
```

- 主人主动互动：动作树完成后立即 `Social -= 25`
- 狗主动互动：动作树完成后进入 `WaitingResponse`
- 人类回应：`Social -= 20`
- 动物回应：`Social -= 15`
- 30 秒无回应或明确拒绝：Social 不变
- 重复、过期、目标不匹配或 interactionId 不匹配的反馈不会结算
- 等待回应期间不重复发起社交
- Lv.0-Lv.3 非社交行为可以中断执行中或等待中的社交，执行 `Social -= 20`
- 本期社交成功、拒绝、超时和中断不修改情绪值

性格预设：

- `GentleCompanion`：`A/O/E/C = 85/75/30/40`
- `SunnyExplorer`：`90/80/95/70`
- `LoyalGuardian`：`70/90/70/90`
- `ProudIndependent`：`40/30/60/80`

当前提供 Joy、Excite、Anxiety、Curious、Calm 的性格系数计算接口，但这些系数尚未应用到现有情绪增量。

### 7.7 Exploration 探索

当前状态：已实现晨起初始化、自然增长、空间/物品动作树和结果结算。

语义与配置：

- `Exploration` 越高表示探索欲望越强
- 默认值：`10`
- 晨起值：`round(random(10, 20) * k_curious)`
- `k_curious = (E/50) * (1 + 0.3*(1-C/100))`
- 触发阈值：`Exploration > 60`
- 满溢阈值：`Exploration > 80`

自然增长：

- `06:00-21:00` 且 `Energy > 50`：每 10 分钟 `Exploration += 5`
- 其他时间或 `Energy <= 50`：不增长
- 凌晨仍遵循全局需求锁定规则

行为和动作树：

- 主动探索为 Lv.4，输出 `ACTION_EXPLORE`
- 新/旧目标和环境变化为 Lv.2，输出 `ACTION_OBJECT_EXPLORE`
- 空间探索每次从空间动作池随机抽取 1 个动作，成功后 `Exploration -= 15`
- 物品探索根据锁定目标选择拖鞋/袜子、垃圾桶、快递盒、纸巾、门或通用物品动作池
- 人物或地图目标使用观察类动作

新旧目标：

- 感知可通过 `is_new`、`novelty` 或 `discovery_type` 显式指定
- 未指定时，核心使用进程内 `targetId` 集合判断
- 首次识别为 `New`，成功后 `Exploration -= 20`
- 再次识别同一目标为 `Old`，成功后 `Exploration -= 10`
- 待执行或执行中的同一目标不会被持续视觉重复覆盖
- 主动探索被高优先级行为打断时，执行全局 `Exploration -= 20`

已知目标集合暂时只保存在内存中，重启后会重新开始判断。

## 8. 外部事件和感知适配

核心事件入口是 `PostEvent(eventTag, metadata)`。事件会进入 `pendingEvents`，下一次 `Tick()` 被仲裁器消费。

当前 `SensorInputAPI` 提供：

- `OnVoiceInput(soundType, direction, confidence)`
- `OnVisionInput(visionType, metadata)`
- `OnTouchInput(touchType, position, pressure)`
- `OnEnvironmentChange(contextType, value)`

ROS2 感知适配已按 `docs/MarsDog感知理解层ROS2说明文档.md` 接入：

- 订阅 `/perception/observation`
- 订阅 `/perception/interaction_event`

由于当前仓库没有正式 ROS2 自定义 msg/srv，第一版使用 `std_msgs/String` 承载 JSON，字段名与文档保持一致。

当前映射：

| 输入 | 条件 | 核心事件/状态 |
|---|---|---|
| `/perception/observation` | `faces[]` 或 `humans[]` 非空 | 更新人类目标可见性，不生成主人主动事件 |
| `/perception/observation` | `tracked_objects[].label` 为 dog/cat/animal | `AnimalApproach` 并更新动物目标可见性 |
| `/perception/observation` | 其他 `tracked_objects[]` 非空 | 按 targetId 生成 `NewObject / OldObject` 并锁定探索目标类型 |
| `/perception/interaction_event` | `event_type=wakeup` | `OwnerCall` |
| `/perception/interaction_event` | `event_type=speech` | `VoiceInput` |
| `/perception/interaction_event` | `event_type=intent` 且主人交互类命令 | `OwnerCall` |
| `/perception/interaction_event` | `event_type=intent` 其他命令 | `Intent` |
| `/perception/interaction_event` | `event_type=danger` | `Danger / Pain / Weightlessness` |
| `/perception/interaction_event` | `state=lights_off` | `SetLightsOffValue(True)` 并立即刷新困倦 |
| `/perception/interaction_event` | `state=lights_on` | `SetLightsOffValue(False)` |
| `/perception/interaction_event` | `state=owner_left_home` | `OnOwnerPresenceChanged(False)`，Social 单次 `+30` |

`wakeup / speech / 主人交互 intent` 在 10 秒窗口内合并为一个主人互动回合。

ROS2 输出：

- `marsdog/action`：当前顶层行为，例如 `ACTION_EAT`
- `marsdog/concrete_actions`：当前顶层行为展开后的 `ACT_*` 序列，以逗号拼接
- `marsdog/action_command`：当前需要动作执行层执行的单个 `ACT_*` 命令，JSON 格式，包含 `commandId`

ROS2 输入：

- `marsdog/action_feedback`：动作执行层反馈，JSON 格式
- `marsdog/social_feedback`：人类或动物对狗主动社交的回应，JSON 格式

注意：感知文档里的 `/dog/perception_task` service 当前还没有实现 client 调用。后续涉及找物、识别人脸、确认人在不在视野内等行为时，需要接入该 service。

动作反馈 JSON 示例：

```json
{
  "commandId": "cmd-000001",
  "actionName": "ACT_RUN_TO_BOWL",
  "status": "SUCCESS",
  "metadata": {}
}
```

社交反馈 JSON 示例：

```json
{
  "interactionId": "social-000001",
  "targetType": "Human",
  "responseType": "RESPONDED",
  "metadata": {}
}
```

## 9. 当前已配置的 ACTION 行为树

| 顶层行为 | 当前配置状态 |
|---|---|
| `ACTION_EAT` | 已配置激动进食和正常进食动作树 |
| `ACTION_SLEEP` | 已配置入睡动作树；睡眠深度由状态机控制 |
| `ACTION_DEFECATE` | 已配置排泄动作树 |
| `ACTION_GROOM` | 已配置清洁动作树 |
| `ACTION_RECHARGE` | 已配置低电量和严重低电量动作树 |
| `ACTION_SOCIAL_GREET` | 已配置主人回应和动物问候动作树 |
| `ACTION_ATTENTION_SEEK` | 已配置可见人类互动及寻找主人动作树 |
| `ACTION_PLAY_INVITE` | 已配置人类和动物邀请玩耍动作树 |
| `ACTION_RESOURCE_SHARE` | 已配置对人资源互动动作树 |
| `ACTION_BOUNDARY_TEST` | 已配置动物边界试探动作树 |
| `ACTION_EXPLORE` | 已配置空间探索动作池 |
| `ACTION_SPACE_EXPLORE` | 已配置空间探索动作池 |
| `ACTION_OBJECT_EXPLORE` | 已配置特定物品、人物/地图和通用物品动作树 |
| 情绪表达类行为 | 未配置具体动作树 |

未配置动作树的行为仍可被仲裁输出，但 `GetConcreteActionQueue()` 会返回顶层行为名本身。

## 10. 当前测试覆盖

当前使用标准库 `unittest`。

运行方式：

```bash
python3 -m unittest discover -s tests
```

已覆盖：

- 需求 API 读写和范围限制
- 情绪 API、回调、行为结果情绪映射
- 事件 API
- 优先级仲裁
- 行为树推进和中断
- 饥渴、排泄、困倦、清洁、精力需求逻辑
- 社交增长、目标选择、会话状态机和回应结算
- 探索增长、新旧目标识别、空间/物品动作树和结果结算
- 性格预设与情绪性格系数
- 动作命令生成和执行反馈闭环
- ROS2 动作反馈 JSON 适配
- ROS2 社交回应和动物目标适配
- 动作配置结构
- 感知理解层 ROS2 JSON 适配
- 调试状态接口

## 11. 当前主要缺口

1. 探索已知目标没有持久化。
   - 当前已知 targetId 只保存在进程内存中，重启后会重新视为新目标。

2. ROS2 自定义消息和 service 尚未生成。
   - 当前 `/perception/observation` 和 `/perception/interaction_event` 用 `std_msgs/String` JSON 临时承载。
   - `/dog/perception_task` service 尚未接入。

3. 行为执行反馈已有最小闭环，但还没有超时/取消策略。
   - 当前已支持 `SUCCESS / FAILURE / INTERRUPTED`。
   - 还没有动作超时重试、取消命令、执行节点健康检查等策略。

4. 社交性格系数尚未作用到情绪变化。
   - 当前只提供公式计算接口。
   - 社交结果本期不会修改 Joy、Excite、Anxiety、Curious 或 Calm。

5. 外部正在运行的动作尚未统一纳入核心状态。
   - 例如外部运动节点正在执行跟随主人，如果没有写入核心状态，核心系统无法自动感知和取消该外部动作。

## 12. 后续建议顺序

建议优先级：

1. 在现有 `action_command / action_feedback` 基础上补充超时、取消、重试策略。
2. 接入 `/dog/perception_task` service client。
3. 为探索已知目标增加可选持久化。
4. 决定社交结果何时正式作用到情绪性格系数。
5. 用正式 ROS2 msg/srv 替换当前 JSON String 临时协议。
