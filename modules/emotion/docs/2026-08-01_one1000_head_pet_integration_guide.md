# ONE1000 临时摸头传感器联调指南

## 1. 实现结果

全迹 ONE1000 的哨兵雷达摸头位已转换为现有情绪事件
`EVT_TACTILE_HEAD_PET`，不需要修改情绪配置中的事件名。

数据链路：

```text
ONE1000 UART 0x54 bit1
  -> one1000_tactile_node
  -> /perception/tactile_event
  -> emotion_engine_node
  -> 情绪数值与 /emotion/signal_event
```

需求节点也订阅触觉 Topic，但当前摸头不会修改 Hunger、Energy、Social 等内部需求。

## 2. 硬件和串口

- 波特率：`115200`
- 数据格式：`8N1`
- 当前机器识别结果：ONE1000 为 `/dev/ttyUSB1`
- 当前机器稳定路径：
  `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AP2315SD-if00-port0`
- `/dev/ttyUSB0` 当前是 CH340 IMU，不能作为 ONE1000 使用。

建议联调使用 by-id 路径，USB 拔插后设备编号变化也不会串错设备：

```bash
ls -l /dev/serial/by-id/
```

本实现依据资料目录中的
`ONE1000软件资料/串口通信协议和解析参考/ONE1000_AOA定位和雷达_串口协议_V1.6_20260317.pdf`：
UART 帧头为 `55 AA`，CRC 使用 `CRC16-XMODEM`，`0x4A` 控制哨兵，`0x54`
状态 bit1 表示摸头，`0x57` 设置摸头阈值，`0x59` 为每秒心跳。

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
ls -l /dev/ttyUSB1
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
  serial_port:=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AP2315SD-if00-port0 \
  touch_threshold:=30 \
  touch_cooldown_seconds:=1.0
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

`/one1000/status` 固定为真实时间 1 Hz；`/perception/tactile_event` 只在摸头上升沿
发布，不能用 `hz` 判断它是否正常。

正常启动日志依次包含：

```text
ONE1000 serial opened
ONE1000 heartbeat
ONE1000 command sent: set touch threshold=30
ONE1000 command sent: clear sentry cache
ONE1000 command sent: start sentry
ONE1000 heartbeat: ... radar=0x05
```

有效摸头后会看到：

```json
{
  "schema_version": "1.0",
  "event_type": "EVT_TACTILE_HEAD_PET",
  "source": "ONE1000",
  "sensorType": "UWB_RADAR",
  "touchState": "STARTED"
}
```

连续保持手不放只发一次。需要松手，再次摸头，并满足默认1秒真实时间冷却，
才会发布下一次事件。冷却不受虚拟时间倍率影响。

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
  one1000_serial_port:=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AP2315SD-if00-port0 \
  one1000_touch_threshold:=30 \
  one1000_touch_cooldown_seconds:=1.0
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
`EMO_JOY_TRIGGERED`；松手并在默认1秒冷却结束后尽快第二次有效摸头，Joy 会先
按真实时间略微衰减，再增加25（通常约48），从而发布一次该事件。这不表示
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
  "sensorType": "UWB_RADAR",
  "touchState": "STARTED",
  "rawStatus": 3,
  "livingBodyDetected": true,
  "maxRadarValue": 42.5,
  "livingBodyFirstIndex": 17
}
```

计算只依赖 `event_type`，其余 ONE1000 字段用于硬件调试。触觉输入是外部真实事件，
因此不附加 `timeContext`；由它产生的情绪信号仍会附加当前权威虚拟时间上下文。

`/one1000/status` 使用相同的 `std_msgs/msg/String` 和 `schema_version=1.0`，按
真实时间 1 Hz 发布。重点字段：

- `connected`：最近2.5秒内是否收到心跳。
- `heartbeat.radarState`：正常启动后应为 `ACTIVE`。
- `heartbeat.radarActive`：正常启动后应为 `true`。
- `sentryStatus.headTouchDetected`：ONE1000 原始摸头位。
- `sentryStatus.rawStatus`：bit0 为活体，bit1 为摸头。

如果 `radarActive=true` 但触摸时 `headTouchDetected` 始终为 `false`，问题位于
ONE1000 检测、安装方向或阈值，不是 ROS2 事件转换。如果原始位能变为 `true`，
但 `/perception/tactile_event` 没有消息，再检查边沿与冷却逻辑。

## 7. 参数说明

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `serial_port` | `/dev/ttyUSB1` | 独立 launch 的设备路径 |
| `auto_start_sentry` | `true` | 自动设置阈值、清缓存并启动哨兵 |
| `touch_threshold` | `30` | 厂商摸头阈值，范围 `1-65535` |
| `touch_cooldown_seconds` | `1.0` | 两次事件之间的真实时间冷却 |
| `command_interval_seconds` | `0.3` | 命令间隔，最小0.2秒；节点参数可用 |
| `stop_sentry_on_shutdown` | `true` | Ctrl+C 时停止哨兵并恢复串口配置 |

主联调 launch 中参数名前增加 `one1000_`，例如
`one1000_touch_threshold`。

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
