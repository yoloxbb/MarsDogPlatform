# ONE1000 临时摸头传感器联调指南

## 1. 实现结果

全迹 ONE1000 的 C5 信标距离和哨兵雷达摸头位均可转换为现有情绪事件
`EVT_TACTILE_HEAD_PET`。当前默认使用距离方案，不需要雷达摸头位。

数据链路：

```text
ONE1000 UART 0xC5 distance < 0.10m
  -> one1000_tactile_node
  -> /perception/tactile_event
  -> emotion_engine_node
  -> 情绪数值与 /emotion/signal_event
```

需求节点也订阅触觉 Topic，但当前摸头不会修改 Hunger、Energy、Social 等内部需求。

## 2. 硬件和串口

- 波特率：`115200`
- 数据格式：`8N1`
- 当前机器识别结果：ONE1000 为 `/dev/ttyUSB0`
- 当前机器稳定路径：
  `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AG00S82A-if00-port0`

建议联调使用 by-id 路径，USB 拔插后设备编号变化也不会串错设备：

```bash
ls -l /dev/serial/by-id/
```

本实现依据资料目录中的
`ONE1000软件资料/串口通信协议和解析参考/ONE1000_AOA定位和雷达_串口协议_V1.6_20260317.pdf`：
UART 帧头为 `55 AA`，CRC 使用 `CRC16-XMODEM`，`0xC5` 的小端 float 距离单位
为米；`0x4A` 控制哨兵，`0x54` 状态 bit1 表示雷达摸头，`0x57` 设置雷达阈值，
`0x59` 为每秒心跳。

## 3. 构建和加载环境

在项目根目录执行：

```bash
cd /home/bird/Marsdog
source /opt/ros/humble/setup.bash
colcon build --packages-select marsdog_need_emotion
source install/setup.bash
```

如果系统提示串口无权限，确认当前用户属于 `dialout`：

```bash
groups
ls -l /dev/ttyUSB0
```

组权限修改只在确实缺少 `dialout` 时执行，并重新登录：

```bash
sudo usermod -aG dialout "$USER"
```

## 4. 单独验证 ONE1000

终端1启动硬件节点：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/Marsdog/install/setup.bash
ros2 launch marsdog_need_emotion one1000_tactile.launch.py \
  serial_port:=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AG00S82A-if00-port0 \
  detection_mode:=distance \
  distance_threshold_cm:=10.0 \
  touch_cooldown_seconds:=2.0
```

终端2查看摸头原始事件：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/Marsdog/install/setup.bash
ros2 topic echo /perception/tactile_event std_msgs/msg/String --field data
```

使用周期状态确认节点与硬件持续在线：

```bash
ros2 topic hz /one1000/status
ros2 topic echo /one1000/status --field data
```

`/one1000/status` 固定为真实时间 1 Hz；距离持续小于10cm时，
`/perception/tactile_event` 默认每2秒发布一次。没有满足距离条件时不会输出，
因此不能只用 `hz` 判断它是否正常。

距离模式正常启动日志包含：

```text
ONE1000 serial opened
ONE1000 head-pet detection: mode=distance, distance_threshold=10.0cm
```

有效摸头后会看到：

```json
{
  "schema_version": "1.0",
  "event_type": "EVT_TACTILE_HEAD_PET",
  "source": "ONE1000",
  "sensorType": "UWB_DISTANCE",
  "touchState": "STARTED",
  "distanceMeters": 0.075,
  "distanceCentimeters": 7.5,
  "distanceThresholdCentimeters": 10.0
}
```

有效 C5 距离满足 `0 < distance < 0.10m` 时立即触发；0米按无效值处理，恰好
10cm不触发。只要信标持续在10cm内，之后默认每2秒再次发布一次；移到10cm或
更远后停止。重复间隔不受虚拟时间倍率影响。

## 5. 与需求/情绪一起启动

100倍、虚拟00:00启动，并保留00:00-06:00的30秒加速：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/Marsdog/install/setup.bash
ros2 launch marsdog_need_emotion internal_need_emotion.launch.py \
  time_scale:=100 \
  virtual_start_time:=00:00 \
  midnight_acceleration_enabled:=true \
  midnight_duration_seconds:=30 \
  random_seed:=12345 \
  one1000_tactile_enabled:=true \
  one1000_serial_port:=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AG00S82A-if00-port0 \
  one1000_detection_mode:=distance \
  one1000_distance_threshold_cm:=10.0 \
  one1000_touch_cooldown_seconds:=2.0
```

另开终端观察四条 Topic：

```bash
ros2 topic echo /perception/tactile_event --field data
ros2 topic echo /emotion/state --field data
ros2 topic echo /emotion/signal_event --field data
ros2 topic echo /one1000/status --field data
```

默认性格参数下，一次有效摸头的情绪增量为：

| 情绪 | 增量 |
|---|---:|
| Joy | `+25` |
| Calm | `+15` |
| Excite | `+5` |

Joy 初始为0，触发阈值为30，因此第一次摸头后 Joy 为25，不会发布
`EMO_JOY_TRIGGERED`；信标持续保持在10cm内，默认2秒后自动产生第二次事件，
Joy 会先按真实时间略微衰减，再增加25，从而发布一次该事件。这不表示
第一次摸头丢失，可以直接从 `/emotion/state` 看到数值变化。若两次间隔过长，
第一次增加的 Joy 已衰减较多，第二次也可能仍未达到阈值。

## 6. Topic 契约

`/perception/tactile_event`：

- 消息类型：`std_msgs/msg/String`
- QoS：`RELIABLE, KEEP_LAST, depth=10`
- JSON `schema_version`：`1.0`

完整字段：

```json
{
  "schema_version": "1.0",
  "timestamp": 1785556800.0,
  "event_type": "EVT_TACTILE_HEAD_PET",
  "source": "ONE1000",
  "sensorType": "UWB_DISTANCE",
  "touchState": "STARTED",
  "detectionMethod": "DISTANCE_THRESHOLD",
  "distanceMeters": 0.075,
  "distanceCentimeters": 7.5,
  "distanceThresholdCentimeters": 10.0,
  "anchorMacId": 287454020,
  "beaconId": 1432778632,
  "beaconType": 2,
  "positionConfidence": 95
}
```

计算只依赖 `event_type`，其余 ONE1000 字段用于硬件调试。触觉输入是外部真实事件，
因此不附加 `timeContext`；由它产生的情绪信号仍会附加当前权威虚拟时间上下文。

`/one1000/status` 使用相同的 `std_msgs/msg/String` 和 `schema_version=1.0`，按
真实时间 1 Hz 发布。重点字段：

- `connected`：最近2.5秒内是否收到 UART 字节、有效协议包或心跳。
- `detection.mode`：默认 `distance`；旧硬件雷达位方案为 `radar`。
- `detection.distanceTouchActive`：最近有效距离是否小于阈值。
- `protocol.uartActive`：包括固件调试文本在内的 UART 原始活动。
- `protocol.active`：UART数据是否通过外层长度与 CRC 校验。
- `protocol.positionPacketCount`：兼容解析的 `0xC5` 定位包累计数量。
- `position.distanceCentimeters`：当前信标到基站的厘米距离。
- `position.withinTouchThreshold`：当前距离是否满足摸头阈值。
- `commands.sentCount`：节点已向 ONE1000 发送的命令数。
- `commands.responseCount`：ONE1000 已返回的命令响应数。
- `commands.lastResponse`：最近响应及是否成功；没有响应时为 `null`。
- `heartbeat.radarState`：正常启动后应为 `ACTIVE`。
- `heartbeat.radarActive`：正常启动后应为 `true`。
- `sentryStatus.headTouchDetected`：ONE1000 原始摸头位。
- `sentryStatus.rawStatus`：bit0 为活体，bit1 为摸头。

如果 `radarActive=true` 但触摸时 `headTouchDetected` 始终为 `false`，问题位于
ONE1000 检测、安装方向或阈值，不是 ROS2 事件转换。如果原始位能变为 `true`，
但 `/perception/tactile_event` 没有消息，再检查阈值和重复间隔逻辑。

部分 5.1.x 固件持续输出 C5 定位包但没有 `0x59` 心跳，并把 C5 内层长度写成
33、实际携带38字节。当前实现已兼容该精确格式。默认距离模式不会发送哨兵启动
命令，因为当前设备进入哨兵模式后会停止 C5 定位流。正常距离模式应表现为：

```json
{
  "connected": true,
  "protocol": {"positionPacketCount": 31},
  "detection": {"mode": "distance"},
  "position": {"distanceCentimeters": 8.0, "withinTouchThreshold": true},
  "commands": {"sentCount": 0, "responseCount": 0}
}
```

把信标移入10cm内会立即发布一次摸头事件；持续保持时每2秒继续发布。

如果发送哨兵启动命令后出现以下组合：

```json
{
  "connected": true,
  "protocol": {"uartActive": true, "active": false},
  "commands": {"sentCount": 3, "responseCount": 0}
}
```

并且原始串口出现 `session cmd deinit`、`cir Ready`，说明命令实际到达设备，
但设备运行的是雷达调试固件：活动期只输出文本，没有文档要求的 `0x54/0x59`
业务包。该状态无法仅靠上位机解析得到摸头 bit1，需要向厂商索取支持串口协议
V1.6 的正式固件，或取得该调试文本中摸头结果的定义。

## 7. 参数说明

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `serial_port` | `/dev/ttyUSB1` | 独立 launch 的设备路径 |
| `detection_mode` | `distance` | `distance` 使用C5距离；`radar` 使用0x54摸头位 |
| `distance_threshold_cm` | `10.0` | 有效距离严格小于该值时触发 |
| `auto_start_sentry` | `true` | 仅雷达模式自动设置阈值、清缓存并启动哨兵 |
| `touch_threshold` | `30` | 厂商摸头阈值，范围 `1-65535` |
| `touch_cooldown_seconds` | `2.0` | 阈值内重复发布事件的真实时间间隔 |
| `command_interval_seconds` | `0.3` | 命令间隔，最小0.2秒；节点参数可用 |
| `stop_sentry_on_shutdown` | `true` | Ctrl+C 时停止哨兵并恢复串口配置 |

主联调 launch 中参数名前增加 `one1000_`，例如
`one1000_distance_threshold_cm`。

需要切回厂商雷达摸头位时使用：

```bash
ros2 launch marsdog_need_emotion one1000_tactile.launch.py \
  serial_port:=/dev/ttyUSB1 detection_mode:=radar \
  auto_start_sentry:=true touch_threshold:=30
```

厂商手册只给出默认值30，未定义调节方向与灵敏度的稳定关系。建议从默认值开始，
根据实际安装位置小步调整，每次修改后重启节点并同时检查误报和漏报。

## 8. 常见问题

### 有硬件心跳但没有触摸事件

先确认日志中雷达状态已经从 `0x03` 变为 `0x05`。如果仍无事件：

1. 确认触摸的是模块摸头检测对应的安装区域。
2. 从默认30小幅调整 `touch_threshold` 后重启，对比漏报与误报情况。
3. 观察日志是否出现非0的命令响应状态；状态0表示成功。
4. 确认没有其他程序同时打开同一串口。

### 收到摸头 Topic，但没有 `EMO_JOY_TRIGGERED`

这是阈值行为：第一次只把 Joy 从0增加到25，第二次有效摸头才越过30。检查
`/emotion/state` 可以确认第一次已经生效。

### 串口打开失败或设备路径变化

使用 `/dev/serial/by-id/...` 稳定路径，并用以下命令确认占用者：

```bash
fuser -v /dev/ttyUSB1
```

不要停止或改用 `/dev/ttyUSB0` 上的 IMU，除非硬件连接已经明确改变。

### Ctrl+C 后雷达仍工作

正常关闭会发送 `0x4A/0x05` 停止命令。若进程被强制杀死而未执行清理，可重新
启动节点后正常 Ctrl+C；节点退出时会再次发送停止命令。

## 9. 同事侧需要做什么

如果同事只消费 `/emotion/state` 或 `/emotion/signal_event`，无需增加任何订阅。
如果需要直接响应摸头动作，则订阅 `/perception/tactile_event`，识别
`event_type == "EVT_TACTILE_HEAD_PET"`。不要依赖 `maxRadarValue` 做业务判断，
它只作为厂商调试值保留。
