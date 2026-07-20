# 2026-07-15 双目 V4L2 相机工作总结

## 1. 文档范围

本文整理 2026-07-15 围绕 `stereo_v4l2_camera` 完成的有效工作，内容以当前源码、相机实际枚举结果和实机日志为依据。

本文有意排除了或修正了中途试验中的过时结论：

- 原 `direct_usb_yuyv_100fps_30fps.launch.py` 的文件名与实际配置不一致，现已改名为 `yuyv_100_to_50fps.launch.py`，明确表示底层采集 100 FPS、ROS 发布 50 FPS。
- OpenVINS 当前 ROS 2 实现使用 `ApproximateTime` 同步双目图像，队列长度为 10，并非严格的 `ExactTime`。
- rqt、`ros2 topic hz` 或 Python 订阅端显示的帧率不一定等于相机底层采集帧率，必须结合节点自己的采集统计判断。
- TST 相机后来只列出 YUYV 1 FPS，并不是固件被修改，而是相机当时只协商到 USB2 480M。

本文主要覆盖以下目录：

```text
/home/bird/robot_ws/imu_ws/src/stereo_v4l2_camera
```

`camera/src/stereo_camera_pkg` 中仍存在其他未提交修改，但不属于本文已经复核的交付范围。

## 2. 最终成果概览

昨天的核心成果可以概括为：

1. V4L2 直采节点现在同时支持 YUYV 和 MJPEG 拼接双目图。
2. 捕获和 ROS 发布被拆成两个线程，发布端变慢时不再直接堵住内核采集流水线。
3. 节点只保留最新一对完整双目帧，优先低延迟，避免旧帧不断排队。
4. 左右图来自同一个 V4L2 缓冲，并使用完全相同的 ROS 时间戳。
5. 节点增加采集帧率、发布帧率和内核序号丢帧统计，可以区分“相机掉帧”和“订阅端显示跟不上”。
6. 相机格式、发布限帧、QoS 深度、可靠性及相机控制项均可配置。
7. 为最新 TST 相机增加普通 20 FPS 启动文件。
8. 为最新 TST 相机增加 OpenVINS/VIO 专用 20 FPS 启动文件。
9. 对 TST 相机在 USB3/YUYV 和 USB2/MJPEG 两种情况下进行了实机验证。

## 3. 涉及的相机与启动文件

### 3.1 通用 USB Camera

启动文件：[usb_mjpeg_60fps.launch.py](../launch/usb_mjpeg_60fps.launch.py)

当前默认配置为：

| 参数 | 当前值 |
|---|---:|
| 拼接分辨率 | 1280×480 |
| 像素格式 | MJPEG |
| 采集帧率 | 60 FPS |
| 默认设备 | 稳定的 `/dev/v4l/by-id/...` 路径 |
| 左右单目输出 | 各 640×480 `mono8` |

该启动文件的相机控制范围对应另一款 USB Camera，不适用于最新 TST 相机。例如其中 `gain=200` 已超过 TST 相机的最大值 190，因此不能直接混用。

### 3.2 只提供 YUYV 100 FPS 离散模式的相机

启动文件：[yuyv_100_to_50fps.launch.py](../launch/yuyv_100_to_50fps.launch.py)

当前实际配置：

| 参数 | 当前值 |
|---|---:|
| 拼接分辨率 | 1280×480 |
| 输入格式 | YUYV |
| 底层采集 | 100 FPS |
| ROS 发布 | 50 FPS |
| 发布策略 | 定时取最新完整双目帧 |

该相机只公布 100 FPS 的 YUYV 离散模式，所以不能要求驱动直接输出 20、30 或 50 FPS。正确做法是底层仍按 100 FPS 采集，然后在独立发布线程中按目标频率取最新帧。

原文件名中的 `_30fps` 是早期目标遗留；新名称 `yuyv_100_to_50fps.launch.py` 已与当前实际配置保持一致。

### 3.3 最新 TST USB3.0 Camera

普通启动文件：[tst_yuyv_20fps.launch.py](../launch/tst_yuyv_20fps.launch.py)

OpenVINS 启动文件：[tst_openvins_20fps.launch.py](../launch/tst_openvins_20fps.launch.py)

稳定设备路径为：

```text
/dev/v4l/by-id/usb-TST_USB3.0_Camera_TST_USB3.0_Camera_01.00.000-video-index0
```

相比 `/dev/video4`，`by-id` 路径不会因为其他摄像头的插拔顺序而轻易改变。

## 4. V4L2 直采节点的有效改动

主程序：[stereo_v4l2_direct_node.cpp](../src/stereo_v4l2_direct_node.cpp)

### 4.1 当前数据流

```text
UVC 相机
   │
   ▼
V4L2 mmap 内核缓冲
   │  捕获线程：DQBUF、时间戳、解码/拆分、立即 QBUF
   ▼
单槽 latest_frame（始终覆盖为最新完整双目帧）
   │  发布线程：不限速发布或按 steady_clock 限帧
   ▼
左图 + 右图 + 两路 CameraInfo
```

这种结构的目标是降低延迟并保护采集线程。发布、订阅或 DDS 短时变慢时，旧帧会被新帧替换，而不是无限堆积。

### 4.2 参数检查与格式选择

`ExecuteValidateParameters()` 的职责：

- 检查拼接图宽度必须为偶数。
- 检查采集帧率、QoS 深度、缓冲数量和超时参数。
- 接受 `YUYV/YUY2` 和 `MJPEG/MJPG` 两组名称。
- 将格式名称归一化为相应的 V4L2 FourCC。

不支持的格式会在节点启动阶段直接报错，不会静默使用其他格式。

### 4.3 YUYV 与 MJPEG 处理

`GetStereoFrameValue()` 的职责是把一张横向拼接图拆成左右两张 `mono8` 图像。

YUYV 路径：

- 不做完整 BGR/RGB 转换。
- 直接提取每两个字节中的 Y 分量。
- 在同一循环内完成左右图拆分。
- 输出总数据量约为输入 YUYV 的一半。

MJPEG 路径：

- 使用 OpenCV `cv::imdecode(..., cv::IMREAD_GRAYSCALE)` 直接解码为灰度图。
- 检查解码后的宽高是否与请求分辨率一致。
- 解码成功后再拆分左右图。
- 解码失败时丢弃该帧并打印警告，不发布损坏图像。

为支持 MJPEG，构建系统增加了 OpenCV `core` 和 `imgcodecs` 依赖：

- [CMakeLists.txt](../CMakeLists.txt)
- [package.xml](../package.xml)

### 4.4 左右图同步与时间戳

每个 V4L2 拼接帧只生成一个 `StereoFrame`，其中左右图：

- 来自同一个内核缓冲；
- 使用同一个 `header.stamp`；
- 使用各自的 `frame_id`；
- 总是作为一对进入最新帧槽。

`GetFrameTimestampValue()` 优先使用 V4L2 驱动提供的 `CLOCK_MONOTONIC` 缓冲时间戳，并映射到当前 ROS 时钟。如果驱动没有提供有效单调时间戳，才回退到节点当前时间。

这保证了 ROS 消息层面的左右同步。两颗传感器实际曝光是否在硬件层面完全同步，仍取决于相机内部硬件设计，不能仅凭 ROS 时间戳反推。

### 4.5 捕获线程与发布线程解耦

`ExecuteCaptureLoop()` 的职责：

- 打开并配置相机；
- 通过 `poll()` 等待帧；
- 从 V4L2 队列取出缓冲；
- 检查序号是否跳变；
- 生成完整双目帧；
- 尽快把内核缓冲重新放回队列；
- 把最新双目帧交给发布线程；
- 设备超时或断开后自动关闭并重连。

`ExecutePublisherLoop()` 的职责：

- `publish_framerate=0` 时，每得到一对新帧就发布；
- `publish_framerate>0` 时，使用 `steady_clock` 固定节拍取最新帧；
- 如果发布端落后，不补发已经过时的历史帧。

这正是“底层 100 FPS、ROS 只输出 50 FPS”能够稳定工作的基础。

### 4.6 只保留最新帧

`ExecuteQueueLatestFrame()` 使用互斥锁保护一个 `latest_frame_` 指针。新帧到达时直接替换旧帧。

优点：

- 延迟不会因为积压不断增加；
- rqt、录包或算法短时变慢时，采集线程仍可继续归还 V4L2 缓冲；
- VIO 总是更倾向处理接近当前时刻的图像。

代价：

- 当发布端确实跟不上时，中间图像会主动被跳过；
- 该策略追求低延迟，不追求“每一张采集图都必须发布”。

### 4.7 左右发布顺序优化

`ExecutePublishFrame()` 按帧序号交替选择先发布左图或右图。

这样做不能让两个 ROS publish 调用真正同时发生，但能避免高负载时始终固定某一侧最后进入 DDS 队列，从而减轻“总是同一目看起来更卡”的偏置。

左右图的时间戳仍然相同，因此 OpenVINS 的双目同步器可以正确配对。

### 4.8 QoS 参数

节点增加：

| 参数 | 含义 | 默认值 |
|---|---|---:|
| `qos_depth` | DDS KeepLast 队列深度 | 4 |
| `reliable_qos` | 是否使用 Reliable | false |

普通传感器显示通常可用 Best Effort 降低阻塞风险；当前 OpenVINS 双目订阅使用 `message_filters::Subscriber` 的默认 ROS 2 QoS，因此 OpenVINS 专用启动文件选择 Reliable，以保证发布端与订阅端兼容。

Reliable 并不等于永不掉帧。如果接收端、DDS 或内存带宽长期不足，仍可能出现延迟、覆盖或上层处理跳帧。

### 4.9 相机控制管理

节点会在格式和帧率协商后设置相机控制，避免驱动重新协商时恢复自动模式。

每个控制在写入前会检查：

- 控制是否存在；
- 是否被驱动禁用；
- 请求值是否在范围内；
- 是否满足步长要求。

写入后会再次读回，确认实际值与请求值一致。

`disabled_camera_controls` 用于跳过某款相机没有提供或当前处于 inactive 状态的控制，避免因为一个不存在的控制导致整个设备反复重连。

新增的 VIO 相关可选控制：

| 参数 | 对应作用 | `-1` 的含义 |
|---|---|---|
| `exposure_dynamic_framerate` | 是否允许曝光动态改变帧率 | 不修改 |
| `focus_automatic_continuous` | 连续自动对焦 | 不修改 |
| `focus_absolute` | 固定焦距位置 | 不修改 |

### 4.10 自恢复与运行统计

节点遇到以下情况会关闭并重新打开设备：

- `poll()` 超时；
- USB 设备挂起或断开；
- `DQBUF/QBUF` 失败；
- STREAMON 或初始化失败。

节点每约 5 秒打印：

```text
Direct capture: xx.xx fps, topic publish: xx.xx fps, kernel sequence drops: N
```

三个字段分别代表：

- `Direct capture`：节点实际从 V4L2 取得并成功处理的帧率；
- `topic publish`：发布线程实际发布双目帧对的频率；
- `kernel sequence drops`：根据 V4L2 帧序号跳变统计的底层丢帧数。

判断问题时应优先看这行，而不是只看 rqt 的视觉流畅度。

## 5. 最新 TST 相机的普通配置

[tst_yuyv_20fps.launch.py](../launch/tst_yuyv_20fps.launch.py) 显式开启相机的自动曝光和自动白平衡，更适合普通预览。该文件没有主动设置对焦控制。

| 参数 | 值 |
|---|---:|
| 拼接输入 | 1280×480 YUYV |
| 左右输出 | 各 640×480 `mono8` |
| 原生采集/发布 | 20 FPS |
| 缓冲数 | 4 |
| QoS | Reliable，深度 4 |
| 曝光模式 | Aperture Priority，`auto_exposure=3` |
| 自动白平衡 | 开启 |
| 自动对焦 | 不修改，保留设备当前状态 |
| `poll_timeout_ms` | 3000 ms |

`poll_timeout_ms` 设为 3000 ms 是因为该相机实测在第一次 STREAMON 后会出现约 1.04 秒的启动停顿。使用原先 1000 ms 超时会把正常启动过程误判为掉线并不断重连。

V4L2 控制可能在设备保持供电时继续保留。如果先运行 OpenVINS 文件关闭了自动对焦，再运行普通文件，普通文件不会自动把连续自动对焦重新打开；需要重启相机或显式设置相应控制。

## 6. OpenVINS/VIO 专用配置

### 6.1 相机端参数

[tst_openvins_20fps.launch.py](../launch/tst_openvins_20fps.launch.py) 使用以下默认值：

| 参数 | 默认值 | VIO 目的 |
|---|---:|---|
| 拼接分辨率 | 1280×480 | 每目输出 640×480 |
| 帧率 | 20 FPS | 与 OpenVINS 跟踪频率对齐 |
| 默认格式 | YUYV | 避免 JPEG 压缩伪影 |
| `publish_framerate` | 0 | 发布每个原生 20 FPS 帧 |
| `auto_exposure` | 1 | 手动曝光，避免亮度逐帧变化 |
| `exposure_time_absolute` | 100 | 10 ms，降低运动模糊 |
| `exposure_dynamic_framerate` | 0 | 禁止曝光改变帧率 |
| `gain` | 128 | 固定增益 |
| 自动白平衡 | 关闭 | 避免图像特征外观随时间变化 |
| 白平衡温度 | 4650 K | 固定白平衡 |
| 电源频率 | 1，即 50 Hz | 适配本地照明频率 |
| 锐度 | 64 | 减少过强锐化产生的光晕和噪声边缘 |
| 背光补偿 | 16 | 使用设备最小值，减少动态画面处理 |
| 连续自动对焦 | 关闭 | 保持相机内参稳定 |
| 固定焦距 | 359 | 保留当时设备报告的焦距位置 |
| QoS | Reliable，深度 4 | 匹配当前 OpenVINS 双目订阅 |

V4L2 的 `exposure_time_absolute` 单位为 100 微秒，因此 100 对应 10 ms。

10 ms 是降低运动模糊与保证室内亮度之间的初始折中，不是所有环境下的最终最优值。如果画面过暗，建议先缓慢提高固定增益；如果噪声过大，再适当增加固定曝光，但应避免接近 50 ms 的整帧周期。

`focus_absolute=359` 只是当时相机在自动对焦状态下报告的位置。安装位置或工作距离改变后，需要在目标工作距离重新找清晰焦点，再把该值固定下来。

### 6.2 ROS 话题

OpenVINS 专用启动文件默认重映射为：

| 数据 | 话题 | 编码/类型 |
|---|---|---|
| 左目图像 | `/cam0/image_raw` | `sensor_msgs/Image`, `mono8` |
| 右目图像 | `/cam1/image_raw` | `sensor_msgs/Image`, `mono8` |
| 左目 CameraInfo | `/cam0/camera_info` | `sensor_msgs/CameraInfo` |
| 右目 CameraInfo | `/cam1/camera_info` | `sensor_msgs/CameraInfo` |
| WIT IMU | `/imu/data_raw` | `sensor_msgs/Imu` |

图像话题、CameraInfo 话题和 `frame_id` 都可以通过 launch 参数覆盖。

### 6.3 当前 OpenVINS 源码的实际行为

本机 OpenVINS 位于：

```text
/home/bird/robot_ws/openvins_ws/src/open_vins
```

当前 ROS 2 双目订阅行为是：

- 默认图像话题为 `/cam0/image_raw` 和 `/cam1/image_raw`；
- 使用 `message_filters::sync_policies::ApproximateTime`；
- 同步队列长度为 10；
- 输入图像最终转换为 `MONO8`；
- `track_frequency` 的代码默认值为 20 Hz，但具体数据集配置文件可能覆盖为 21 Hz 或 31 Hz。

因此实际使用的 `estimator_config.yaml` 仍应明确设置：

```yaml
use_stereo: true
max_cameras: 2
track_frequency: 20.0
```

OpenVINS 会从 Kalibr 配置中的 `rostopic` 读取话题，因此还需要确保：

```yaml
cam0:
  rostopic: /cam0/image_raw
  resolution: [640, 480]

cam1:
  rostopic: /cam1/image_raw
  resolution: [640, 480]

imu0:
  rostopic: /imu/data_raw
```

以上片段只说明话题和分辨率，不包含可用的标定数值。

### 6.4 必须重新标定的内容

更换相机后不能沿用旧相机的以下参数：

- 左右相机内参；
- 畸变参数；
- 左右相机外参和基线；
- 相机与 IMU 的旋转和平移；
- 相机与 IMU 的时间偏移；
- IMU 噪声密度和随机游走参数。

当前包内的 [left.yaml](../config/left.yaml) 和 [right.yaml](../config/right.yaml) 是已有标定文件，但没有证据证明它们属于最新 TST 相机。

OpenVINS 专用启动文件没有发布普通启动文件中那组旧的静态 TF，这是有意设计：相机到 IMU、左右目之间的几何关系必须来自新相机的实际标定，不能用旧相机或估算值代替。

节点仍会加载并发布包内 CameraInfo，但 OpenVINS 主要使用自己的 Kalibr YAML。新标定完成前，不应把当前 CameraInfo 当成最新相机的有效标定。

## 7. 实机验证结果

### 7.1 TST 相机在 USB3、YUYV 20 FPS 下

在相机正确协商到 USB3 5000M、驱动公布 YUYV 1280×480 20 FPS 时，实测结果为：

```text
Direct capture: 20.02～20.04 fps
topic publish:  20.02～20.04 fps
kernel sequence drops: 0
```

稳定阶段相邻帧间隔约为 50 ms，符合原生 20 FPS。

单独使用 `ros2 topic hz` 测量任意一目时，可观察到约 20.03 FPS。

### 7.2 USB2 降级时的格式变化

后来同一 TST 相机实际枚举在 USB2 480M。该状态下驱动公布：

```text
YUYV 1280×480：1 FPS
MJPEG 1280×480：可用 20 FPS
```

这不是固件变化。UVC 设备和驱动可以根据当前 USB 链路速度、可用带宽及接口 alternate setting 动态公布不同帧间隔。

YUYV 1280×480 20 FPS 的纯图像载荷约为：

```text
1280 × 480 × 2 字节 × 20 ≈ 24.6 MB/s
```

实际 USB 传输还包含协议开销。USB3 高速触点、线材、Hub、供电或握手异常时，相机可能退回 USB2，即使用户没有刷固件或修改驱动。

### 7.3 USB2 下的 MJPEG 回退验证

使用以下覆盖参数启动：

```bash
pixel_format:=MJPEG
```

相机经历一次重新枚举后，稳定阶段实测：

```text
Direct capture: 20.02～20.04 fps
topic publish:  20.02～20.04 fps
kernel sequence drops: 0
```

MJPEG 是 USB2 下保持 20 FPS 的临时方案。它会增加主机 JPEG 解码开销，并可能引入压缩伪影；正式运行 OpenVINS 时仍优先推荐 USB3 + YUYV。

### 7.4 构建与测试

包已经通过：

```bash
colcon build --packages-select stereo_v4l2_camera --symlink-install
```

包级 6 项测试均报告通过：

- flake8；
- pep257；
- uncrustify；
- lint_cmake；
- xmllint；
- cppcheck 测试项。

其中系统中的 cppcheck 2.7 因 ROS 检查脚本已知性能问题而被跳过实际分析，但测试项本身返回通过；其他列出的检查实际执行并通过。

## 8. 关于“订阅后帧率下降”的正确结论

### 8.1 订阅不会主动修改相机硬件帧率

正常 ROS 订阅不会向 V4L2 相机发送“降低帧率”的命令。订阅增加的是：

- ROS 消息序列化和反序列化；
- DDS 数据复制与传输；
- 内存带宽；
- 图像转换；
- GUI 缩放与渲染；
- 订阅回调处理时间。

如果这些工作让发布线程或接收线程跟不上，就会表现为话题接收帧率下降、画面卡顿或消息延迟。

### 8.2 为什么 rqt 打开后可能从 50 FPS 看到约 40 FPS

rqt 图像插件不仅订阅消息，还要做图像格式处理、缩放和 GUI 刷新。高频 640×480 双目图会产生明显 CPU 和内存压力。

对于底层 100 FPS、发布 50 FPS 的配置，打开 rqt 后观察到约 40 FPS，并不能单独证明相机掉帧。应同时查看节点日志：

- 如果 `Direct capture` 仍为目标值且 `kernel sequence drops=0`，底层相机没有掉帧；
- 如果 `topic publish` 仍为目标值，瓶颈在订阅端或测量工具；
- 如果 `topic publish` 自身下降，才说明发布/DDS 路径也受到压力；
- 如果 `Direct capture` 和内核序号都异常，才继续排查 USB、驱动或相机。

### 8.3 为什么同时测左右目时数值可能不一致

同时运行两个 Python `ros2 topic hz`，会让两个进程都反序列化大图。测试中出现过左右接收数值不一致，但节点自身仍保持目标采集和发布帧率。

原因可能包括：

- Python 回调调度差异；
- DDS 接收队列和线程调度；
- 左右 publish 调用不可能在同一 CPU 指令时刻完成；
- GUI 或终端工具处理速度不足；
- Reliable 队列在高负载下产生不同等待。

交替左右发布顺序可以减轻固定偏置，但不能保证两个独立订阅程序拥有完全相同的处理能力。

### 8.4 为什么 D435i 往往表现更稳定

D435i 使用专门的图像处理硬件、硬件时间戳和成熟的 librealsense 数据管线，USB 流、缓存和同步都经过针对性优化。

当前普通 UVC 双目相机输出的是一张横向拼接图，主机还需要完成：

- UVC 接收；
- 可选 JPEG 解码；
- 左右拆分；
- 灰度提取；
- 两路 ROS 消息发布。

因此两者不能只根据分辨率和标称 FPS 直接比较。D435i 也可能在 USB 带宽不足、CPU 过载或订阅端过慢时掉帧，只是其完整软硬件管线通常更成熟。

### 8.5 双系统 Ubuntu 为什么不一定明显比虚拟机流畅

原生 Ubuntu 去除了虚拟机 USB 转发和虚拟化调度开销，但如果实际瓶颈是以下任一项，体验仍可能相近：

- 相机只协商到 USB2；
- 相机固件或 UVC 驱动行为；
- 自动曝光导致运动模糊；
- rqt 渲染速度；
- DDS/内存复制；
- CPU 单核处理能力；
- 相机本身左右曝光或输出机制。

所以“原生系统”是必要的优化条件之一，但不会自动解决所有相机链路问题。

## 9. rosbag 录制与回放结论

### 9.1 录包是否会掉帧

录包本质上也是订阅者，因此有可能掉帧，但不是必然。

当前 20 FPS 双目输出为两张未压缩 `mono8` 图，每秒图像有效载荷约为：

```text
640 × 480 × 1 字节 × 2 目 × 20 ≈ 12.3 MB/s
```

还需要加上 ROS、DDS、数据库和文件系统开销。SSD 通常可以承担该量级，但 CPU、磁盘、QoS、同时运行的算法和 rqt 都会影响结果。

需要注意：即使相机输入使用 MJPEG，节点发布的仍是解码后的未压缩 `mono8`，所以直接录 `/cam0/image_raw` 和 `/cam1/image_raw` 不会按 MJPEG 输入大小写盘。

### 9.2 录制时未写入的帧无法恢复

如果录制阶段已经漏掉某些图像，之后播放 bag 不会重新产生这些帧。

应在录制后检查：

- 左右图消息数量；
- 时间戳是否单调；
- 左右时间戳是否能成对；
- 相邻图像时间差是否接近 0.05 秒；
- IMU 是否覆盖全部相机时间范围。

### 9.3 播放后再订阅是否会掉帧

可能，取决于播放速度、QoS 和订阅算法处理能力。

- bag 中存在且订阅端来得及处理：可以完整接收；
- 播放过快或订阅端过慢：接收端仍可能漏帧或积压；
- 使用较慢播放倍率：更容易完整处理；
- OpenVINS 的 `track_frequency` 低于输入频率：OpenVINS 会按自身频率主动跳过部分图像。

因此“先录再播”可以把在线相机采集与离线算法计算解耦，但不能自动消除录制阶段或回放订阅阶段的性能限制。

## 10. 推荐使用方法

### 10.1 编译

```bash
cd /home/bird/robot_ws/imu_ws
colcon build --packages-select stereo_v4l2_camera --symlink-install
source install/setup.bash
```

### 10.2 最新 TST 相机普通预览

相机必须正确连接到 USB3，并确认 YUYV 20 FPS 存在：

```bash
ros2 launch stereo_v4l2_camera tst_yuyv_20fps.launch.py
```

### 10.3 最新 TST 相机用于 OpenVINS

USB3 + YUYV 推荐命令：

```bash
ros2 launch stereo_v4l2_camera tst_openvins_20fps.launch.py
```

USB2 临时 MJPEG 回退：

```bash
ros2 launch stereo_v4l2_camera \
  tst_openvins_20fps.launch.py \
  pixel_format:=MJPEG
```

现场调节固定曝光、增益和焦距：

```bash
ros2 launch stereo_v4l2_camera \
  tst_openvins_20fps.launch.py \
  exposure_time_absolute:=120 \
  gain:=140 \
  focus_absolute:=359
```

调参时每次只改变一个量，并在机器人实际运动速度和工作光照下检查特征点数量与运动模糊。

### 10.4 检查 USB 链路

```bash
lsusb -t
```

TST 相机对应行应显示 `5000M`，而不是 `480M`。

检查相机当前公布的模式：

```bash
v4l2-ctl \
  -d /dev/v4l/by-id/usb-TST_USB3.0_Camera_TST_USB3.0_Camera_01.00.000-video-index0 \
  --list-formats-ext
```

### 10.5 检查运行状态

```bash
ros2 topic info -v /cam0/image_raw
ros2 topic info -v /cam1/image_raw
```

`ros2 topic hz` 可以辅助检查，但对高带宽图像的测量会受到 Python 工具本身性能影响。最终应同时结合相机节点每 5 秒输出的底层统计。

## 11. 已知限制与后续工作

### 11.1 新相机尚未完成可靠标定

在完成新相机的 Kalibr 双目 + IMU 联合标定前，不能认为 OpenVINS 已经具备可用精度。固定曝光和稳定帧率只能改善输入质量，不能替代几何与时间标定。

### 11.2 普通启动文件中的静态 TF 不是新标定结果

普通启动文件仍包含已有的静态 TF 数值。这些值必须通过机械尺寸或标定确认，不能默认视为最新 TST 相机与 IMU 的真实外参。

### 11.3 CameraInfo 可能属于旧相机

当前节点默认加载包内 `left.yaml/right.yaml`。在确认标定来源之前，使用这些 CameraInfo 做校正、深度计算或其他视觉算法存在风险。

### 11.4 USB2 不适合作为最终 YUYV 方案

如果相机只显示 480M，应优先检查：

1. 是否经过 Hub 或转接器；
2. USB3 线材是否完整支持 SuperSpeed；
3. 插头高速触点是否接触良好；
4. USB 口供电是否稳定；
5. 重新插拔后是否恢复 5000M。

不需要因为一次 USB2 降级就刷固件。

### 11.5 当前节点未严格拒绝所有帧率协商偏差

节点会打印驱动实际接受的帧率；当设置了发布限帧且实际采集低于发布目标时会拒绝启动。但 `publish_framerate=0` 时，只要驱动返回正帧率，当前实现不会强制要求它必须等于请求值。

因此在 USB2 下请求 YUYV 20 FPS、驱动实际返回 1 FPS 时，必须查看启动日志中的 `Configured ... @ x.xxx fps`。后续可以增加 `strict_framerate` 检查，避免错误链路下继续运行。

### 11.6 建议的后续顺序

1. 确保 TST 相机长期稳定枚举为 USB3 5000M。
2. 在固定曝光、固定增益、固定焦距下完成双目标定。
3. 完成相机与 WIT IMU 的联合标定和时间偏移估计。
4. 新建专用 OpenVINS 配置目录，不修改示例数据集配置。
5. 使用 `track_frequency: 20.0` 做在线和 rosbag 离线测试。
6. 对比节点底层统计、bag 消息完整性和 OpenVINS 特征跟踪耗时。
7. 最后再决定使用 YUYV 还是 MJPEG、Reliable 还是 Best Effort。

## 12. 最终结论

昨天正确且已经落地的主线不是单纯“把 FPS 改成某个数字”，而是把相机链路改造成：

- 底层按设备真实离散模式采集；
- 捕获与发布解耦；
- 始终处理完整、最新的双目帧对；
- 使用同一采集缓冲时间戳；
- 用节点自身统计区分采集、发布和订阅端问题；
- 为 VIO 固定曝光、增益、白平衡和焦距；
- 根据 USB3/USB2 实际协商结果选择 YUYV 或 MJPEG；
- 把相机稳定性优化与 OpenVINS 标定严格区分。

在 USB3 + YUYV 20 FPS 条件下，最新 TST 相机已经验证可以稳定采集和发布，内核序号丢帧为 0。下一阶段真正决定 VIO 效果的关键工作，是确认 USB3 链路稳定，并完成最新相机与 IMU 的联合标定。
