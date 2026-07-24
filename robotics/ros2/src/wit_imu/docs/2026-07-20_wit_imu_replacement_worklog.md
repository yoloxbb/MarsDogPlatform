# 2026-07-20 WIT IMU 更换、诊断与 200 Hz 配置记录

## 1. 文档目的

本文记录同型号 WIT IMU 更换后，ROS 2 话题 `/imu/data_raw` 没有数据的问题定位、硬件配置和最终验证过程。

重点不是复述所有试错过程，而是保留以后可以直接复用的正确步骤、判断依据和容易踩坑的地方。

涉及目录：

```text
/home/bird/robot_ws/imu_ws/src/wit_imu
```

## 2. 问题现象

原启动文件 [wit_imu.launch.py](../launch/wit_imu.launch.py) 固定使用：

```text
串口：/dev/ttyUSB0
波特率：115200
预期频率：200 Hz
话题：/imu/data_raw
```

旧 IMU 使用该配置时能稳定发布约 200 Hz。换成同型号、同版本的新 IMU 后：

- ROS 节点可以正常启动；
- `/imu/data_raw` 话题和发布者存在；
- 话题没有消息，统计频率为 `0.00 Hz`；
- 节点日志显示串口成功打开；
- 每 5 秒收到约 5800～6000 个字节，但全部被解析器丢弃；
- 校验错误为 0，没有识别到有效的 WIT 数据帧。

典型日志如下：

```text
Opened /dev/ttyUSB0 @ 115200 baud, publishing imu/data_raw at 200.0 Hz
IMU: 0.00 Hz, checksum errors=0, discarded bytes=5793
```

这说明问题不在 ROS 话题名，也不是设备完全没有输出，而是电脑收到的数据无法按当前串口参数解析。

## 3. 最终结论

新旧 IMU 虽然型号和版本相同，但设备内部保存的非易失配置不同：

| 项目 | 旧 IMU | 新 IMU 刚接入时 | 新 IMU 最终配置 |
|---|---:|---:|---:|
| 波特率 | 115200 | 9600 | 115200 |
| 输出频率 | 200 Hz | 10 Hz | 200 Hz |
| 协议 | WIT 标准二进制协议 | WIT 标准二进制协议 | WIT 标准二进制协议 |
| 帧头 | `0x55` | `0x55` | `0x55` |

原 launch 用 115200 打开一个实际工作在 9600 的 IMU，因此 UART 解码出的数据是乱码。串口可以成功 `open()`，也可能持续读到字节，但这些字节不是有效的 `55 51/52/...` 帧，所以驱动不会发布消息。

真正解决问题的操作是：

1. 先以 9600 正确读取新 IMU，确认协议和出厂输出频率；
2. 通过 WIT 官方串口命令修改 IMU 内部寄存器；
3. 将硬件设置为 115200 baud、200 Hz；
4. 保存配置；
5. 将 launch 默认参数同步为 115200、200 Hz；
6. 分别从原始串口和 ROS 话题两层验证真实频率。

## 4. 驱动的数据要求

当前 C++ 节点为 [wit_imu_node.cpp](../src/wit_imu_node.cpp)。它读取 WIT 标准二进制协议：

```text
每帧长度：11 字节
帧头：0x55
0x51：三轴加速度
0x52：三轴角速度
0x53：融合角度，data_raw 模式下忽略
0x54：磁场，当前节点忽略
```

节点必须先收到有效的 `0x51` 加速度帧，再收到有效的 `0x52` 角速度帧，才会组装并发布一条 `sensor_msgs/msg/Imu` 消息。

因此，即使串口波特率正确，如果设备关闭了加速度或角速度输出，话题仍然可能是 0 Hz。

## 5. 正确的诊断步骤

### 5.1 停止占用串口的节点

抓取原始串口前，必须停止所有 IMU 节点和串口工具。同一个串口不应同时被两个 ROS 节点或上位机读取。

检查占用：

```bash
fuser -v /dev/ttyUSB0
```

如果有进程占用，应先正常停止对应程序，不要直接让两个程序竞争串口。

### 5.2 确认设备节点和权限

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
id
udevadm info --query=property --name=/dev/ttyUSB0
```

本次设备实际信息：

```text
设备：/dev/ttyUSB0
USB 转串口芯片：CH341
USB VID：1a86
设备权限组：dialout
```

当前用户属于 `dialout`，所以不需要使用 `sudo` 运行 ROS 节点。

### 5.3 在常见波特率下抓取原始数据

不要只根据产品型号猜波特率。可以依次测试常见值：

```bash
mkdir -p /tmp/wit_serial_capture

for baud in 9600 19200 38400 57600 115200 230400; do
  stty -F /dev/ttyUSB0 "$baud" raw -echo -ixon -ixoff -crtscts
  timeout 2s dd \
    if=/dev/ttyUSB0 \
    of="/tmp/wit_serial_capture/baud_${baud}.bin" \
    bs=16384 \
    status=none

  echo "BAUD=$baud"
  wc -c "/tmp/wit_serial_capture/baud_${baud}.bin"
  od -An -v -tx1 -N 88 "/tmp/wit_serial_capture/baud_${baud}.bin"
done
```

注意：`timeout` 到时会返回状态码 124。这表示命令按计划被定时结束，不代表抓包文件没有数据。如果脚本开了 `set -e`，需要单独处理这个返回值，否则后续统计命令不会执行。

本次只有 9600 能读取到连续有效帧：

```text
55 51 ... checksum
55 52 ... checksum
55 53 ... checksum
55 54 ... checksum
```

在 9600 下，两秒抓到 880 字节：

```text
4 种输出帧 × 11 字节 × 10 组/秒 × 2 秒 = 880 字节
```

因此可以确定新 IMU 当时实际为 9600 baud、10 Hz，并且启用了加速度、角速度、角度和磁场输出。

### 5.4 不要仅凭“串口有字节”判断配置正确

波特率不匹配时，USB 转串口芯片仍可能交付大量错误解码的字节。因此以下日志不能证明通信参数正确：

```text
Opened /dev/ttyUSB0 @ 115200 baud
```

正确判断标准是：

- 能连续找到 `0x55` 帧头；
- 11 字节校验和正确；
- 帧类型稳定出现 `0x51`、`0x52`；
- 按帧数计算出的频率合理。

## 6. 推荐的硬件配置步骤

### 6.1 配置前提

以下命令只适用于已经确认使用 WIT 标准通信协议、发送 `0x55` 十一字节帧的设备。

WIT 写寄存器的通用格式为：

```text
FF AA 寄存器地址 数据低字节 数据高字节
```

本次使用的命令：

| 二进制命令 | 含义 |
|---|---|
| `FF AA 69 88 B5` | 解锁配置寄存器 |
| `FF AA 03 0B 00` | 设置输出频率为 200 Hz |
| `FF AA 04 06 00` | 设置串口波特率为 115200 |
| `FF AA 00 00 00` | 保存配置 |

官方协议说明：

<https://wit-motion.gitbook.io/witmotion-sdk/wit-standard-protocol/wit-standard-communication-protocol>

### 6.2 推荐顺序：先修改波特率，再修改输出频率

9600 baud 的 8N1 串口理论上最多约传输 960 字节/秒。当前设备每组输出 4 个十一字节帧，200 Hz 需要：

```text
4 × 11 × 200 = 8800 字节/秒
```

所以 9600 无法承载当前输出内容的 200 Hz 数据。推荐先提高波特率，再设置 200 Hz，避免设备先进入低波特率高输出率的拥塞状态。

#### 第一步：确认串口未被占用

```bash
fuser -v /dev/ttyUSB0
```

#### 第二步：在旧波特率 9600 下写入 115200

```bash
stty -F /dev/ttyUSB0 9600 raw -echo -ixon -ixoff -crtscts

# 解锁。
printf 'ffaa6988b5' | xxd -r -p > /dev/ttyUSB0
sleep 0.2

# 设置设备波特率为 115200。
printf 'ffaa040600' | xxd -r -p > /dev/ttyUSB0
sleep 0.2

# 尝试在旧波特率下保存，兼容“保存后才切换波特率”的固件。
printf 'ffaa000000' | xxd -r -p > /dev/ttyUSB0
sleep 1
```

`xxd -r -p` 会把十六进制文本转换为真正的二进制字节。例如：

```text
字符串 ffaa040600
        ↓ xxd -r -p
字节   FF AA 04 06 00
```

#### 第三步：电脑端切换到 115200，并再次保存

不同固件对 BAUD 寄存器的生效时机可能不同。有的立即切换，有的在保存或重启后切换。因此电脑端切换到新波特率后，再执行一次解锁和保存更稳妥：

```bash
stty -F /dev/ttyUSB0 115200 raw -echo -ixon -ixoff -crtscts

# 在新波特率下重新解锁。
printf 'ffaa6988b5' | xxd -r -p > /dev/ttyUSB0
sleep 0.2

# 在新波特率下再次保存。
printf 'ffaa000000' | xxd -r -p > /dev/ttyUSB0
sleep 1
```

执行后应先在 115200 下抓取一小段数据，确认还能看到有效的 `55 51/52/53/54` 帧，再继续修改输出频率。

#### 第四步：在 115200 下设置 200 Hz

```bash
stty -F /dev/ttyUSB0 115200 raw -echo -ixon -ixoff -crtscts

# 解锁。
printf 'ffaa6988b5' | xxd -r -p > /dev/ttyUSB0
sleep 0.2

# 设置为 200 Hz。
printf 'ffaa030b00' | xxd -r -p > /dev/ttyUSB0
sleep 0.2

# 保存。
printf 'ffaa000000' | xxd -r -p > /dev/ttyUSB0
sleep 1
```

配置完成后，建议重新上电一次，再按第 7 节重新验证，以确认非易失保存生效。

## 7. 配置后的原始串口验证

### 7.1 抓取两秒数据

```bash
stty -F /dev/ttyUSB0 115200 raw -echo -ixon -ixoff -crtscts

timeout 2s dd \
  if=/dev/ttyUSB0 \
  of=/tmp/wit_after_200hz.bin \
  bs=16384 \
  status=none

wc -c /tmp/wit_after_200hz.bin
od -An -v -tx1 -N 88 /tmp/wit_after_200hz.bin
```

本次实测结果：

```text
抓取时间：约 2 秒
总字节数：17584
有效 0x51 加速度帧：400
有效 0x52 角速度帧：400
有效 0x53 角度帧：399
有效 0x54 磁场帧：399
估算采样频率：400 / 2 = 200.0 Hz
```

开头数据为：

```text
55 51 ...
55 52 ...
55 53 ...
55 54 ...
```

串口层确认 200 Hz 后，再进行 ROS 层验证。否则只修改 launch 中的数字没有意义。

## 8. ROS 2 启动与验证

### 8.1 启动文件

原启动文件：

```text
launch/wit_imu.launch.py
```

新增的可配置启动文件：

```text
launch/wit_imu_new.launch.py
```

新增文件的最终默认值：

```text
port=/dev/ttyUSB0
baud=115200
expected_rate_hz=200.0
topic=imu/data_raw
```

两个启动文件当前传给驱动的有效参数相同，因此硬件配置完成后都能工作。新文件的主要区别是支持命令行覆盖：

```bash
ros2 launch wit_imu wit_imu_new.launch.py \
  port:=/dev/ttyUSB0 \
  baud:=115200 \
  expected_rate_hz:=200.0
```

### 8.2 构建

```bash
cd /home/bird/robot_ws/imu_ws
source /opt/ros/humble/setup.bash

colcon build \
  --packages-select wit_imu \
  --symlink-install \
  --allow-overriding wit_imu
```

### 8.3 启动

```bash
source /opt/ros/humble/setup.bash
source /home/bird/robot_ws/imu_ws/install/setup.bash

ros2 launch wit_imu wit_imu_new.launch.py
```

也可以继续使用原文件：

```bash
ros2 launch wit_imu wit_imu.launch.py
```

### 8.4 检查话题

另开终端：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/robot_ws/imu_ws/install/setup.bash

ros2 topic hz /imu/data_raw
ros2 topic echo /imu/data_raw --once
```

最终实测：

```text
ros2 topic hz：约 199.5 Hz
节点内部统计：约 199.3～199.4 Hz
checksum errors：0
discarded bytes：通常为 0
```

短时启动或刚接管串口时出现极少量丢弃字节，可能是从半个帧中间开始读取造成的；持续运行后应恢复为 0。

## 9. 本次代码和设备改动

### 9.1 代码改动

新增：

```text
src/wit_imu/launch/wit_imu_new.launch.py
```

该文件把以下参数声明为 launch 参数：

- `port`
- `baud`
- `expected_rate_hz`

未修改：

- 原 `wit_imu.launch.py`；
- C++ 串口读取与解析驱动；
- ROS 话题名称和消息类型。

### 9.2 IMU 硬件改动

向新 IMU 的非易失配置写入：

```text
BAUD = 0x06   -> 115200
RRATE = 0x0B  -> 200 Hz
SAVE = 0x0000 -> 保存
```

这一步才是原启动文件后来也能正常工作的根本原因。

## 10. 关键坑点

### 10.1 同型号不等于内部配置相同

设备型号、固件版本相同，并不保证以下设置相同：

- 波特率；
- 输出频率；
- 输出内容；
- 通信协议模式；
- 安装方向、量程和滤波参数。

更换设备后应把串口配置当成未知值重新确认，不能直接套用旧设备参数。

### 10.2 `expected_rate_hz` 不会配置硬件

launch 中的：

```python
'expected_rate_hz': 200.0
```

只用于驱动内部时间戳推算和频率期望，不会向 IMU 发送 `FF AA 03 0B 00`，也不会把实际 10 Hz 的设备变成 200 Hz。

真实硬件频率必须通过设备寄存器配置，并通过原始帧数验证。

### 10.3 `stty` 只修改电脑端串口

```bash
stty -F /dev/ttyUSB0 115200 ...
```

只是让 Linux/CH341 以 115200 解码 UART，并没有修改 IMU 内部波特率。只有写入 WIT 的 BAUD 寄存器并保存，才能改变设备端配置。

### 10.4 串口打开成功不等于数据正确

设备节点存在、权限正常、`open()` 成功，仅表示 Linux 可以打开 CH341。它不能证明：

- IMU 与电脑波特率一致；
- 数据是 WIT 标准协议；
- 输出内容包含加速度和角速度；
- 校验和正确。

必须结合原始十六进制数据和驱动统计判断。

### 10.5 9600 无法承载当前输出内容的 200 Hz

当前每组包含四个 11 字节帧，200 Hz 需要约 8800 字节/秒。9600 baud 的 8N1 串口有效上限约 960 字节/秒，所以必须同时提高波特率。

只修改输出频率而不提高波特率，设备可能自动降频、出现丢帧，或者让串口长期处于拥塞状态。

### 10.6 修改波特率后，电脑端必须同步切换

发送：

```text
FF AA 04 06 00
```

之后 IMU 会切到 115200。电脑仍以 9600 读取时，立即会看到乱码或没有有效帧。必须执行：

```bash
stty -F /dev/ttyUSB0 115200 ...
```

ROS launch 中的 `baud` 也必须同步修改。

### 10.7 必须解锁并保存

WIT 配置命令应遵循：

```text
解锁 -> 修改寄存器 -> 保存
```

缺少解锁时，设备可能忽略写入；缺少保存时，重新上电后可能恢复旧值。

### 10.8 不要让多个程序同时读取串口

以下程序不能同时占用 `/dev/ttyUSB0`：

- 原 IMU launch；
- 新 IMU launch；
- WIT Windows/Linux 上位机；
- `dd`、串口终端或自定义测试程序。

抓包或写配置前先运行：

```bash
fuser -v /dev/ttyUSB0
```

### 10.9 话题存在不代表正在发布消息

ROS 节点会在读取串口前创建 publisher，因此以下命令可能显示话题和发布者存在：

```bash
ros2 topic list
ros2 topic info /imu/data_raw
```

但设备数据无法解析时，消息频率仍然是 0。必须使用：

```bash
ros2 topic hz /imu/data_raw
ros2 topic echo /imu/data_raw --once
```

### 10.10 `/dev/ttyUSB0` 不一定长期稳定

USB 串口编号取决于设备枚举顺序。插入其他 USB 串口设备后，新 IMU 可能变成 `/dev/ttyUSB1`。

每次设备结构变化后至少检查：

```bash
ls -l /dev/ttyUSB*
udevadm info --query=property --name=/dev/ttyUSB0
```

如果系统同时连接多个同类 CH341，建议后续创建基于 USB 物理路径或独立序列号的 udev 规则，避免依赖动态编号。

## 11. 以后更换 IMU 的推荐检查清单

1. 停止所有使用串口的 ROS 节点和上位机。
2. 用 `ls -l`、`udevadm` 确认实际设备节点。
3. 用 `fuser` 确认串口没有被占用。
4. 从 9600、115200 等常见波特率抓取原始数据。
5. 确认是否为连续、校验正确的 `55 51/52/...` 标准帧。
6. 根据两秒内的 `0x51` 帧数计算真实采样频率。
7. 确认输出内容至少包含 `0x51` 和 `0x52`。
8. 需要 200 Hz 时，先把设备和电脑都切到足够高的波特率。
9. 按“解锁、修改、保存”顺序配置硬件。
10. 重新上电并再次抓包，确认配置持久化。
11. 让 launch 的 `port`、`baud` 和 `expected_rate_hz` 与硬件一致。
12. 最后使用节点日志和 `ros2 topic hz` 双重验证。

## 12. 最终可用命令

```bash
cd /home/bird/robot_ws/imu_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

ros2 launch wit_imu wit_imu_new.launch.py
```

验证：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/robot_ws/imu_ws/install/setup.bash

ros2 topic hz /imu/data_raw
ros2 topic echo /imu/data_raw --once
```

当前期望结果：

```text
串口：/dev/ttyUSB0 @ 115200
原始采样：200 Hz
ROS 发布：约 199～200 Hz
话题：/imu/data_raw
```
