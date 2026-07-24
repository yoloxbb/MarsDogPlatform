# 2026-07-22 USB 双目相机自动曝光排查与修改总结

本文记录 2026-07-22 对 HB USB 双目相机自动曝光问题的分析、代码修改、参数对照和运行验证。当天主要解决了自动曝光不生效、启动后由亮骤暗、画面周期性忽明忽暗，以及直采节点与 `usb_cam`、`v4l2_camera` 表现不一致的问题。

## 1. 工作目标

最初目标是在以下启动文件基础上增加自动曝光版本：

```text
/home/bird/robot_ws/imu_ws/src/stereo_v4l2_camera/launch/usb_camera_openvins_15fps.launch.py
```

要求如下：

1. 保持 OpenVINS 使用的双目图像尺寸、话题和标定参数不变。
2. 支持自动曝光，并允许软件曝光上限采用相机硬件最大值。
3. 解决画面启动后变暗以及运行中忽暗忽亮的问题。
4. 最终让直采节点的亮度表现与正常工作的 `usb_v4l2.launch.py` 一致。

## 2. 相机硬件与控制能力

相机设备：

```text
/dev/v4l/by-id/usb-USB_Camera_USB_Camera_01.00.00-video-index0
```

设备实际对应 `/dev/video2`，使用 Linux `uvcvideo` 驱动。当天确认的主要曝光控件如下：

| 控件 | 范围或枚举 | 固件默认值 |
| --- | --- | ---: |
| `auto_exposure` | `1` 手动，`3` Aperture Priority | `3` |
| `exposure_time_absolute` | `1～10000` | `156` |
| `backlight_compensation` | `0～100` | `48` |
| `gain` | `0～255` | `100` |

相机使用的真实 V4L2 控件名称是：

```text
auto_exposure
exposure_time_absolute
```

不能直接套用某些 `usb_cam` 配置中的 `exposure_auto`、`exposure_absolute` 名称。

所谓软件曝光“上限无限制”，实际实现为：

```text
software_auto_exposure_max = 0
```

`0` 表示不增加软件上限，自动读取并使用设备硬件最大值。本相机硬件最大曝光值仍为 `10000`，并非真正无限大。

## 3. 完成的代码工作

### 3.1 新增自动曝光启动文件

新增文件：

```text
/home/bird/robot_ws/imu_ws/src/stereo_v4l2_camera/launch/usb_camera_openvins_15fps_auto_exposure.launch.py
```

该文件继续使用：

```text
输入总图：1280 × 400，YUYV，15 FPS
左目输出：640 × 400 mono8
右目输出：640 × 400 mono8
左目话题：/cam0/image_raw
右目话题：/cam1/image_raw
```

没有照搬 `usb_v4l2.launch.py` 的 `1280×480`，因为当前 CameraInfo 和 OpenVINS 标定分辨率是每目 `640×400`。修改高度会造成图像与标定参数不一致。

### 3.2 为直采节点增加软件自动曝光能力

修改文件：

```text
/home/bird/robot_ws/imu_ws/src/stereo_v4l2_camera/src/stereo_v4l2_direct_node.cpp
```

增加的软件自动曝光功能包括：

1. 使用左右目中央区域的灰度均值进行测光。
2. 根据目标亮度、死区和响应系数调整 `exposure_time_absolute`。
3. 支持配置最小值、最大值、更新间隔和响应速度。
4. 最大值为 `0` 时查询并采用设备硬件上限。
5. USB 重连后重新初始化曝光状态。
6. 对参数范围和曝光工作模式进行启动校验。

相关参数：

```text
software_auto_exposure
software_auto_exposure_target
software_auto_exposure_min
software_auto_exposure_max
software_auto_exposure_deadband
software_auto_exposure_update_interval
software_auto_exposure_response
```

该功能保留在节点内，便于以后实验，但最终默认配置已经关闭它。

### 3.3 修正曝光控件设置顺序

新增 `ExecuteConfigureExposureControls()`，根据曝光模式采用不同设置顺序：

手动曝光：

```text
切换手动模式 → 设置 exposure_time_absolute
```

硬件自动曝光：

```text
临时切换手动模式 → 设置初始曝光值 → 最后启用 auto_exposure=3
```

重点是让硬件自动曝光成为最后写入的曝光状态，防止后续写入曝光绝对值干扰固件自动曝光。

## 4. 问题现象与根因

### 4.1 自动曝光看起来没有生效

最初直接使用 `auto_exposure=3` 后，`exposure_time_absolute` 很快回到 `156`，画面也明显变暗，因此看起来像自动曝光没有工作。

实际情况是：

1. 相机已经进入固件自动曝光模式。
2. 该相机在自动模式下仍可能回报固定的 `156`，不能只依赖这个数值判断内部传感器曝光状态。
3. 当背光补偿为 `0` 时，固件选择的整体亮度目标很低，导致画面严重偏暗。

### 4.2 启动后先亮、随后立即变暗

启动初期沿用了之前较大的手动曝光值，因此画面短暂较亮。切换到固件自动曝光后，相机迅速采用默认曝光策略，曝光控件回到 `156`，于是出现由亮骤暗。

这不是 ROS 图像拆分节点导致的，也不是左右目不同步。变化发生在 UVC 相机固件的曝光控制阶段。

### 4.3 软件自动曝光出现忽暗忽亮

软件闭环运行时，曾使用以下参数：

```text
target = 105
deadband = 5
update_interval = 10 帧
response = 0.25
```

运行中观测到：

```text
曝光值约在 4831～5190 之间变化
中央灰度约在 90～122 之间变化
```

逐帧亮度呈块状变化：暗约 10 帧、亮约 10～30 帧，左右目变化完全同步。变化周期与每 `10` 帧更新一次曝光高度一致。

根因是相机曝光控件存在多帧生效延迟。软件闭环在上一条指令尚未完全反映到图像时再次调整，形成过冲和反向调节。期间没有发现其他 `usb_cam`、`v4l2_camera` 或 `v4l2-ctl` 进程抢占控件。

曾将软件控制参数放缓为：

```text
deadband = 15
update_interval = 30 帧
response = 0.1
```

这可以减轻振荡，但最终实测表明，本相机采用固件自动曝光并恢复背光补偿效果更稳定。

## 5. 为什么 usb_v4l2 表现正常

参考文件：

```text
/home/bird/robot_ws/camera/src/stereo_camera_pkg/launch/usb_v4l2.launch.py
```

该文件没有显式填写 `auto_exposure` 和 `backlight_compensation`，但 `v4l2_camera` 会把相机可调控件声明为 ROS 参数，并对未覆盖的控件使用固件默认值。

实际启动日志表明它最终设置为：

```text
brightness = 0
saturation = 38
white_balance_automatic = 0
gamma = 150
gain = 1
backlight_compensation = 48
exposure_time_absolute = 156
auto_exposure = 3
```

它表现稳定的核心原因是：

1. 使用相机固件自动曝光 `auto_exposure=3`。
2. 使用固件默认背光补偿 `48`，大幅提高自动曝光目标亮度。
3. 没有 ROS 软件闭环周期性修改曝光值。
4. 普通图像控件只在启动时设置，不会形成曝光控制振荡。

同一场景下进行的背光补偿对照测试：

| 背光补偿 | 左目全图亮度均值 | 结果 |
| ---: | ---: | --- |
| `0` | `23.17` | 画面很暗 |
| `48` | `95.16` | 亮度正常且稳定 |

恢复 `48` 后连续 30 帧亮度范围为 `94.95～95.42`。这说明背光补偿是此前两套启动方式亮度差异的主要因素，分辨率 `400/480` 不是根因。

## 6. 最终采用的方案

自动曝光启动文件最终切换为硬件自动曝光，默认关闭软件闭环。

| 参数 | 与 `usb_v4l2` 对齐的实测值 | 当前源码默认值 |
| --- | ---: | ---: |
| `brightness` | `0` | `0` |
| `contrast` | `0` | `0` |
| `saturation` | `38` | `38` |
| `hue` | `0` | `0` |
| `white_balance_automatic` | `false` | `false` |
| `gamma` | `150` | `150` |
| `gain` | `1` | `1` |
| `power_line_frequency` | `1` | `1` |
| `sharpness` | `0` | `0` |
| `backlight_compensation` | `48` | `50` |
| `auto_exposure` | `3` | `3` |
| `exposure_time_absolute` | `156` | `156` |
| `software_auto_exposure` | `false` | `false` |

说明：当天完成运行验证时背光补偿为 `48`。文档生成时源码已进一步调整为 `50`，其余参数不变。如果需要严格复现实测基准或完全对齐 `usb_v4l2`，应使用 `48`。

## 7. 最终运行验证

使用背光补偿 `48` 完成最终验证，结果如下：

```text
software_auto_exposure = false
brightness = 0
saturation = 38
white_balance_automatic = 0
gain = 1
backlight_compensation = 48
auto_exposure = 3
exposure_time_absolute = 156
```

连续 60 帧左目亮度统计：

```text
mean = 97.65
min  = 97.55
max  = 97.75
std  = 0.06
```

图像发布状态：

```text
采集/发布频率：约 14.3 FPS
内核序号丢帧：0
```

验证期间未再出现周期性忽暗忽亮。测试结束后，相机节点已正常退出，没有遗留占用摄像头的测试进程。

完成的检查：

1. Python launch 文件语法检查通过。
2. `git diff --check` 通过。
3. `colcon build --packages-select stereo_v4l2_camera --symlink-install` 编译通过。
4. 实机启动和 V4L2 控件回读通过。
5. 连续图像亮度采样通过。

## 8. 启动与检查命令

编译：

```bash
cd /home/bird/robot_ws/imu_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select stereo_v4l2_camera --symlink-install
```

启动：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/robot_ws/imu_ws/install/setup.bash
ros2 launch stereo_v4l2_camera \
  usb_camera_openvins_15fps_auto_exposure.launch.py
```

检查最终曝光状态：

```bash
v4l2-ctl -d /dev/video2 \
  -C brightness \
  -C gain \
  -C backlight_compensation \
  -C auto_exposure \
  -C exposure_time_absolute

ros2 param get /stereo_v4l2_direct_node software_auto_exposure
```

正常情况下应看到：

```text
auto_exposure: 3 (Aperture Priority Mode)
software_auto_exposure: false
```

## 9. 后续使用注意事项

1. 不要同时启动 `usb_cam`、`v4l2_camera` 和 `stereo_v4l2_direct_node` 访问同一个 `/dev/video2`。
2. 不要在节点运行期间使用循环 `v4l2-ctl --set-ctrl` 修改曝光，否则会与相机固件争用控制权。
3. 判断自动曝光是否正常时，应同时观察实际图像亮度和 V4L2 模式，不能只看 `exposure_time_absolute=156`。
4. OpenVINS 更重视连续帧之间的光度稳定性。稳定的硬件自动曝光通常优于响应过快的软件曝光闭环。
5. 如果后续再次出现画面很暗，优先检查 `backlight_compensation` 是否被其他启动文件恢复为 `0`。
6. 如果再次出现周期性忽明忽暗，优先检查 `software_auto_exposure` 是否误设为 `true`。
7. 严格复现当天验证结果时使用背光补偿 `48`；当前源码的 `50` 是在验证后的亮度微调值。

## 10. 今日结论

当天完成了从硬件自动曝光、软件自动曝光到不同 ROS 相机驱动行为的完整对照。最终确认画面过暗的主要原因是背光补偿被设为 `0`，周期性闪烁的主要原因是带多帧延迟的软件曝光闭环发生过冲。

最终方案采用：

```text
相机固件自动曝光 + 背光补偿约 48～50 + 软件曝光闭环关闭
```

该方案保留 `640×400/目` 的 OpenVINS 标定链路，并在实机连续帧测试中获得稳定亮度和零内核序号丢帧。
