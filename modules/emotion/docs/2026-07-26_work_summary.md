# 2026-07-26 工作总结

## 1. 今日工作概览

今天围绕内部需求、情绪时间语义、凌晨联调加速和 ROS2 包名冲突完成了以下工作：

| 工作项 | 当前状态 | 结果 |
|---|---|---|
| Energy 改为电量缺口需求值 | 已完成 | `Energy = 100 - 当前电量百分比`，数值越高越紧急 |
| 情绪自然衰减改为真实时间驱动 | 已完成 | 固定按真实时间 1 Hz 衰减，不随 `time_scale` 加速 |
| 独立凌晨测试模式 | 已完成 | 可用 30 秒离散走完虚拟 `00:00-06:00` 并自动验收 |
| 普通连续运行中的每日凌晨加速 | 已完成 | `00:00-06:00` 可压缩为 30 秒，06:00 后恢复 24 倍并继续运行 |
| 虚拟时间联调协议 | 已完成 | `/simulation/time_state` 作为唯一权威虚拟时间来源 |
| ROS2 包重命名 | 核心配置已完成，收尾未完成 | 已改为 `marsdog_need_emotion`，但测试和现有文档仍有旧包名残留 |

`time_scale=1-24` 整数倍率是此前已经完成的基础能力，今天新增的凌晨加速建立在
24 倍基础模式之上，没有放宽生产倍率的 `1-24` 限制。

## 2. 主要实现内容

### 2.1 Energy 改为电量缺口

原来的 Energy 更接近“剩余电量”，与其他需求“数值越高越紧急”的方向相反。
现在统一改为：

```text
Energy需求值 = 100 - 当前电量百分比
```

主要规则：

- 默认状态和晨起满电均为 `Energy=0`。
- `GetBatteryValue()` 返回 `100-Energy`。
- `SetEnergyBatteryValue(batteryValue)` 先把电量限制在 `0-100`，再保存
  `100-batteryValue`。
- `SetDemandValue("Energy", value)` 仍然直接写入需求值。
- 充电结果中的 `energyValue`、`energy_value`、`batteryValue` 继续表示实际电量
  百分比。
- 默认充电目标 `100%` 对应 `Energy=0`。
- `energyValue=88` 对应 `Energy=12`。

需求等级边界调整为：

| Energy | 实际电量 | 等级 |
|---|---:|---|
| `0-80` | `20%-100%` | `NORMAL` |
| `81-90` | `10%-19%` | `TRIGGERED` |
| `91-100` | `0%-9%` | `OVERFLOW` |阿

探索增长条件同步改为 `Energy < 50`，等价于实际电量大于 `50%`。严格边界保持
不变，实际电量恰好 `50%` 时不增长探索需求。

紧迫度选择逻辑没有扩大比较范围，仍然只在已经触发的需求中比较原始需求值。
Energy 改为电量缺口后，可以和 Hunger、Sleepiness 等需求使用相同的“大值更
紧急”排序语义。

### 2.2 情绪自然衰减改为真实时间驱动

情绪状态仍然跟随虚拟秒发布，因此正常模式下真实发布频率为 `time_scale` Hz；
但情绪自然衰减已经从虚拟 Tick 中拆出，改为使用单调真实时间调度器，每个真实
秒执行一次。

效果：

- `time_scale=1/7/24` 时，相同真实时间产生相同的自然衰减。
- 运行时切换倍率不会额外触发衰减。
- 定时器阻塞后会按完整真实秒补算遗漏的衰减 Tick。
- 凌晨 30 秒加速期间，情绪只自然衰减约 30 秒，不会按 6 个虚拟小时衰减。

### 2.3 独立 30 秒凌晨测试

新增独立测试时间源和 `midnight_test.launch.py`，用于只验证虚拟
`00:00-06:00`：

- 六个虚拟小时拆为 36 个步骤。
- 每一步推进虚拟 10 分钟。
- 默认真实总时长为 30 秒，每步约 `0.833` 秒。
- 可自动响应 `NEED_SLEEPINESS_TRIGGERED`，发送
  `ACTION_SLEEP + STARTED`。
- 到达 06:00 后检查浅睡、深睡、晨起重置和最终清醒状态。
- 通过 `/simulation/midnight_test_result` 发布 `PASSED/FAILED` 后退出。

该模式只用于独立自动验收，不负责和同事的行为模块持续联调。

### 2.4 普通连续模式的每日凌晨加速

在普通 `internal_need_emotion.launch.py` 中新增：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `midnight_acceleration_enabled` | `false` | 是否启用每日凌晨加速 |
| `midnight_duration_seconds` | `30.0` | 虚拟 `00:00-06:00` 使用的真实秒数 |

启用条件：

- 基础 `time_scale` 必须为 `24`。
- 启用后不允许在运行时把基础倍率切换到其他值。
- `virtual_start_time=00:00` 可以在启动后立即验证第一次凌晨流程。

连续时间流程：

```text
当天00:00 ──30秒──> 当天06:00 ──正常24倍──> 次日00:00
    ↑                                             │
    └────────────再次进入30秒凌晨加速─────────────┘
```

一个完整虚拟日的真实耗时约为：

```text
凌晨30秒 + 其余18小时/24倍 = 45分30秒
```

加速期间：

- 基础 `timeContext.scale` 保持 `24`。
- `timeContext.effectiveScale=720`。
- `midnightAcceleration.active=true`。
- 发布 `TIME_ACCELERATED_STEP`，每条推进虚拟 10 分钟。
- 需求节点每个步骤执行一次原有的虚拟 10 分钟需求 Tick。
- 情绪节点只发布一次步骤状态，不补发 600 条中间情绪状态。

到达 06:00 后：

- 执行晨起需求重置。
- 睡眠状态自动切换为 `isSleeping=false`。
- 重新对齐普通虚拟秒调度器。
- `effectiveScale` 恢复为 `24`。
- 节点不退出，继续正常运行。

### 2.5 与同事联调的虚拟时间接口

唯一权威虚拟时间 Topic：

```text
/simulation/time_state
```

消息类型：

```text
std_msgs/msg/String
```

同事主要读取：

- `timeContext.virtualDateTime`：权威虚拟日期时间。
- `timeContext.virtualTimestamp`：虚拟 Unix 时间戳。
- `timeContext.scale`：基础倍率。
- `timeContext.effectiveScale`：当前实际推进倍率。
- `event_type`：时间事件类型。

新增的连续加速事件：

```text
TIME_ACCELERATION_CHANGED
TIME_ACCELERATED_STEP
```

同事如果只订阅 `/internal_need/signal_event`、`/internal_need/state` 并向
`/behavior/result_event` 回传行为结果，现有消息格式不需要修改。但行为节点应
在加速开始前启动，收到 `NEED_SLEEPINESS_TRIGGERED` 后及时发送
`ACTION_SLEEP + STARTED`。

同事如果直接订阅 `/simulation/time_state`，不能假设每条消息只增加一个虚拟
秒，必须直接使用 `virtualDateTime`；`TIME_ACCELERATED_STEP` 每条会增加虚拟
10 分钟。

当前系统没有发布标准 ROS2 `/clock`，因此不能通过 `use_sim_time=true` 获得
这套虚拟时间。

### 2.6 ROS2 包重命名

为避免和同事的 `marsdog_behavior` 包发生 ROS2 包发现冲突，当前包已重命名为：

```text
marsdog_need_emotion
```

已完成的修改：

- `package.xml` 的包名。
- `setup.py` 的 `PACKAGE_NAME`。
- `setup.cfg` 的脚本安装目录。
- `resource/marsdog_need_emotion` 资源标记。
- 配置加载器中的 `get_package_share_directory("marsdog_need_emotion")`。
- 两个 launch 中的 `package="marsdog_need_emotion"`。

节点名和 Topic 名没有修改，双方原有 Topic 联调协议可以继续使用。

当前仍需收尾：

- `tests/test_ros2_package.py` 仍检查旧资源文件和旧包名。
- `README.md` 和 `docs` 目录中的启动命令仍有 `marsdog_behavior` 残留。
- 工作空间中可能仍保留旧的 `install/marsdog_behavior` 构建产物，需要在停止
  ROS2 节点后清理并重新构建。

## 3. 可复现步骤

### 3.1 清理重命名前的旧包构建产物

先停止当前工作空间启动的 ROS2 节点。确认目录位于
`/home/bird/Marsdog` 后，只清理旧包对应的生成目录：

```bash
cd /home/bird/Marsdog
rm -rf /home/bird/Marsdog/build/marsdog_behavior
rm -rf /home/bird/Marsdog/install/marsdog_behavior
```

不要删除源码目录。`build` 和 `install` 都是 `colcon` 生成物，重新构建后会
恢复。

### 3.2 构建新包

```bash
cd /home/bird/Marsdog
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select marsdog_need_emotion
source install/setup.bash
ros2 pkg prefix marsdog_need_emotion
```

最后一条命令应输出当前工作空间中的安装路径。

### 3.3 启动连续 24 倍和每日凌晨 30 秒加速

```bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=24 \
  virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345
```

### 3.4 观察权威虚拟时间和需求状态

分别打开终端并加载环境：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/Marsdog/install/setup.bash
```

观察虚拟时间：

```bash
ros2 topic echo /simulation/time_state --field data
```

观察需求状态：

```bash
ros2 topic echo /internal_need/state --field data
```

观察需求等级变化：

```bash
ros2 topic echo /internal_need/signal_event --field data
```

### 3.5 手动模拟同事的睡眠开始结果

收到 `NEED_SLEEPINESS_TRIGGERED` 后执行：

```bash
ros2 topic pub --once /behavior/result_event std_msgs/msg/String \
  "{data: '{\"event_id\":\"continuous-midnight-sleep-001\",\"action_type\":\"ACTION_SLEEP\",\"demand_type\":\"Sleepiness\",\"result_type\":\"STARTED\",\"metadata\":{}}'}"
```

预期结果：

1. 凌晨加速期间 `/internal_need/state.sleep.isSleeping=true`。
2. 睡眠深度从 `Shallow` 进入 `Deep`。
3. 约 30 秒后虚拟时间到达 06:00。
4. 晨起重置后 `isSleeping=false`。
5. 时间节点继续按 24 倍运行，不会自动退出。

### 3.6 运行独立凌晨自动测试

```bash
ros2 launch marsdog_need_emotion midnight_test.launch.py \
  scenario_duration_seconds:=30 \
  completion_hold_seconds:=2 \
  auto_start_sleep:=true \
  random_seed:=12345
```

查看测试结果：

```bash
ros2 topic echo /simulation/midnight_test_result --field data --full-length
```

### 3.7 运行代码验证

```bash
cd /home/bird/Marsdog
python3 -m compileall -q marsdog_core marsdog_ros2 tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
colcon build --packages-select marsdog_need_emotion
git diff --check
```

截至本总结生成时：

- `compileall`：通过。
- 新包 `marsdog_need_emotion` 的 `colcon build`：通过。
- 功能修改和连续凌晨加速在包重命名前曾达到 128 项测试全部通过。
- 包重命名后当前测试为 128 项中的 127 项通过、1 项失败。
- 唯一失败是 `test_ros2_package_metadata_exists` 仍查找
  `resource/marsdog_behavior` 并断言旧包名，不是运行逻辑失败。

更新该测试和文档中的旧包名后，应重新执行完整测试并以 128 项全部通过作为
最终验收条件。

## 4. 实际联调验证结果

连续模式已经实际验证：

1. 使用 `time_scale=24`、`virtual_start_time=00:00` 和 30 秒凌晨加速启动。
2. 日志显示凌晨加速从 00:00 开始。
3. 手动发送 `ACTION_SLEEP + STARTED`。
4. 虚拟约 05:00 时观察到 `isSleeping=true`、`sleepDepth=Deep`。
5. 约 30 秒后到达 06:00，日志显示恢复连续 24 倍。
6. 06:00 后观察到晨起需求值、`isSleeping=false`、
   `effectiveScale=24`。
7. 所有节点保持运行，未在 06:00 自动退出。

独立凌晨测试也已验证 36 个虚拟 10 分钟步骤、自动睡眠握手和最终结果发布。

## 5. 工作过程中遇到的问题及解决方法

### 5.1 Energy 的紧迫度方向和其他需求相反

问题：

- 原 Energy 表示剩余电量，数值越高反而越不紧急。
- 紧迫度只比较已经触发的需求时，Energy 和其他需求无法直接使用同一排序方向。

解决：

- 把 Energy 改为电量缺口。
- 对外硬件电量字段仍保持百分比语义，在 API 边界进行转换。
- 保留“只在已经触发的需求中比较”的原逻辑。

经验：

- 同一排序系统中的指标应先统一方向和单位语义。
- 如果外部协议已经稳定，优先在系统边界转换，避免要求所有上游一起修改。

### 5.2 情绪衰减被时间倍率放大

问题：

- 如果情绪衰减由虚拟秒 Tick 驱动，24 倍模式会让情绪以 24 倍真实速度恢复。

解决：

- 使用独立的单调真实时间调度器。
- 虚拟 Tick 继续负责状态发布时间线，真实 Tick 只负责自然衰减。

经验：

- “虚拟世界发生频率”和“真实体验持续时间”应分别建模。
- 真实计时应优先使用单调时钟，避免系统时间校准导致跳变。

### 5.3 生产倍率限制为 24，但凌晨测试需要等效 720 倍

问题：

- 直接把 `time_scale` 设置为 720 会破坏 `1-24` 参数契约和现有计算节点校验。

解决：

- 基础 `scale` 保持 24。
- 把六小时拆为 36 个虚拟 10 分钟步骤。
- 使用 `effectiveScale` 表示测试期间的实际推进倍率。
- 使用明确的 `TIME_ACCELERATED_STEP` 事件表达跳步。

经验：

- 配置倍率和场景有效倍率应分开表达。
- 大跨度测试更适合离散业务步进，而不是暴力提高高频定时器频率。

### 5.4 06:00 恢复普通 Tick 时可能重复或遗漏

问题：

- 离散时间跳步结束后，如果继续使用旧的逐秒调度器锚点，可能补算整段凌晨，
  或重复发布 06:00 附近的 Tick。

解决：

- 每个凌晨步骤重新锚定权威虚拟时间。
- 结束时把普通虚拟秒调度器明确对齐到 06:00。
- 后续从 06:00 之后继续按 24 倍推进。

经验：

- 时间模式切换必须同时处理权威时间锚点、业务 Tick 序列和调度器下一边界。
- 不能只修改显示时间而不重建调度状态。

### 5.5 测试节点在定时器回调中直接关闭 ROS2 会挂起

问题：

- 独立凌晨测试最初在定时器回调中直接调用 `rclpy.shutdown()`，执行器可能无法
  正常退出。

解决：

- 测试完成时抛出专用完成异常。
- 在节点主循环外层捕获后统一销毁节点并关闭 ROS2。

经验：

- ROS2 节点退出应由执行器外层统一管理。
- 定时器回调适合更新状态和发出完成信号，不适合直接销毁整个运行时。

### 5.6 30 秒流程可能让外部行为模块错过一次性需求事件

问题：

- `/internal_need/signal_event` 只在等级变化时发布一次。
- 整个凌晨只有 30 秒，行为节点如果晚启动，可能错过
  `NEED_SLEEPINESS_TRIGGERED`。

解决：

- 联调时先启动同事的订阅节点，再启动时间和需求节点。
- 行为模块除监听 signal 外，也可以读取 `/internal_need/state.triggered` 和
  `sleep.isSleeping` 进行状态补偿。

经验：

- 一次性事件负责通知，持续状态负责恢复。
- 快速测试场景必须考虑订阅建立顺序和晚加入节点。

### 5.7 ROS2 同名包发生覆盖

问题：

- 双方都使用 `marsdog_behavior` 时，同一工作空间会出现重复包名；不同 overlay
  先后 `source` 时也会互相覆盖。

解决：

- 将需求和情绪包改名为 `marsdog_need_emotion`。
- Topic 保持不变，避免破坏双方联调接口。

当前遗留：

- 测试和文档中的旧包名需要继续批量更新。
- 旧的 `install/marsdog_behavior` 是构建产物，不是源码；重命名后应清理。

经验：

- ROS2 包名、Python distribution 名、ament resource 标记、launch 中的
  `package` 和配置 share 查找必须一致。
- 改包名后必须清理旧安装前缀，否则 `ros2 pkg` 仍可能发现旧包。

## 6. 可积累的工程经验

1. 需求值最好统一为“数值越高越紧急”，外部物理量在 API 边界转换。
2. 排序前先筛选是否触发，可以避免正常需求参与行为竞争。
3. 虚拟时间、真实时间和测试有效时间是三个不同概念，应分别建模。
4. 长虚拟时段的快速测试应以业务 Tick 为粒度离散推进，避免制造无意义的高频
   消息。
5. 时间状态消息应携带权威绝对时间，消费者不要依赖消息次数推算时间。
6. 倍率切换和离散跳步后要显式重建调度器锚点，防止补算风暴和重复 Tick。
7. ROS2 一次性事件需要配套持续状态，保证晚加入节点能够恢复当前状态。
8. ROS2 包重命名必须同时更新包清单、安装入口、资源标记、share 查找、launch、
   测试和文档。
9. `build/`、`install/`、`log/` 是可重建产物，应保持在 Git 忽略列表中。
10. 每次协议或包结构调整后，都应执行 Python 编译、完整单元测试、ROS2 包构建
    和一次实际 Topic 联调。

## 7. 后续待办

1. 把 `tests/test_ros2_package.py` 中的旧包名改为
   `marsdog_need_emotion`。
2. 把 `README.md` 和全部 `docs/*.md` 中的 `ros2 run/launch/build`
   命令改为新包名。
3. 清理旧 `build/marsdog_behavior` 和 `install/marsdog_behavior`。
4. 重新构建 `marsdog_need_emotion`。
5. 重新运行 128 项测试，确认全部通过。
6. 重新执行一次使用新包名的 30 秒连续凌晨联调。

