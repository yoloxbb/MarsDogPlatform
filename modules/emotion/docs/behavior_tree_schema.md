# ACTION 内部行为树配置规范

本文档规定 `configs/actions.yaml` 的配置结构，方便多人新增和维护 `ACTION_*` 内部行为树。

## 总体结构

```yaml
schemaVersion: 1
randomPolicy:
  mode: sample_without_replacement
actions:
  ACTION_NAME:
    - name: 分支名称
      condition:
        demand: Hunger
        operator: gt
        threshold: 70
      fixedSteps: []
      phaseOrder: []
      randomSelection: {}
      randomStepsByPhase: {}
```

`actions` 下的每个 `ACTION_*` 是一个分支列表。分支按列表顺序匹配，先匹配的先执行，因此更高阈值或更特殊的分支必须放在前面。

## 固定动作分支

固定动作分支使用 `steps`：

```yaml
- name: 激动进食
  condition: {demand: Hunger, operator: gt, threshold: 90}
  steps:
    - ACT_RUN_TO_BOWL
    - ACT_FAST_LICK_AND_SWALLOW
```

固定动作会按顺序执行，适合动作很少且顺序明确的行为。

## 随机阶段分支

随机阶段分支使用 `fixedSteps`、`phaseOrder`、`randomSelection` 和 `randomStepsByPhase`：

```yaml
- name: 正常进食
  condition: {demand: Hunger, operator: gt, threshold: 70}
  fixedSteps:
    - ACT_RUN_TO_BOWL
  phaseOrder:
    - prepare
    - eat
    - interaction
    - finish
  randomSelection:
    prepare: {count: 1}
    eat: {count: 1}
    interaction: {count: 1}
    finish: {count: 1}
  randomStepsByPhase:
    prepare:
      - ACT_SNIFF_BOWL_EDGE
```

执行顺序固定为：

```text
fixedSteps -> phaseOrder 中声明的各阶段随机动作
```

当前随机策略是 `sample_without_replacement`，即同一阶段内不重复抽取动作。

## 字段要求

- `schemaVersion` 必须为 `1`。
- `randomPolicy.mode` 当前只支持 `sample_without_replacement`。
- `name` 必须清晰表达分支含义。
- `condition` 可选；无条件分支作为兜底分支时应放在列表最后。
- `steps` 和 `randomStepsByPhase` 二选一，不要同时使用。
- 使用 `randomStepsByPhase` 时必须同时声明：
  - `phaseOrder`
  - `randomSelection`
  - 每个阶段的动作池
- `phaseOrder`、`randomSelection`、`randomStepsByPhase` 的阶段集合必须一致。
- 所有具体动作名称必须使用 `ACT_*`。

## 新增行为步骤

1. 在 `types.py` 的 `ConcreteActionType` 中增加新的 `ACT_*`。
2. 在 `configs/actions.yaml` 中增加或修改对应 `ACTION_*` 分支。
3. 如果是新顶层行为，确认 `configs/priorities.yaml` 能输出该 `ACTION_*`。
4. 如果行为完成后需要回写状态，在 `behavior_engine.py` 的行为成功处理处接入 `Execute*` 接口。
5. 为配置结构、动作序列和行为完成回写补充测试。

## 当前已接入行为

- `ACTION_EAT`
  - `Hunger > 90`：固定动作分支。
  - `Hunger > 70`：固定 `ACT_RUN_TO_BOWL`，再从准备、进食、互动、结束阶段各抽 1 个动作。
- `ACTION_SLEEP`
  - `Sleepiness > 65`：入睡分支。
  - 是否允许触发睡眠由 `SleepinessBehaviorAPI` 的时间状态判断控制：白天且非强制清醒可触发，凌晨或关灯强制触发。
  - 深睡不再由动作树直接选择，而是在浅睡 3 个 Tick 后由睡眠状态机切换。
  - 每次从准备入睡、睡眠中小动作、起床动作三个阶段各抽 1 个动作。
- `ACTION_DEFECATE`
  - `Bladder > 75`：排泄分支，遵循优先级表。
  - 每次从准备、排泄中、结束阶段各抽 1 个动作。
- `ACTION_GROOM`
  - `Cleanliness > 70`：清洁分支，遵循优先级表。
  - 每次从处理毛发动作池中随机抽取 1 个动作。
- `ACTION_RECHARGE`
  - `Energy < 10`：严重低电量分支，先返回充电桩，再执行找不到充电桩时的原地求助动作。
  - `Energy < 20`：低电量分支，从原地喘气、反抗往前走、动作变慢中随机抽取 1 个动作。
