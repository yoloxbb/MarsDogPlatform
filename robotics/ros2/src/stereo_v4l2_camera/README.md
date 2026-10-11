# stereo_v4l2_camera 双目采集

该 C++ 包通过 V4L2 mmap 读取一个左右拼接的 USB 双目设备，支持 YUYV/MJPEG，拆分为两幅 `mono8` 图像并同步发布 CameraInfo。可配置设备控制、软件自动曝光、左右互换、发布时间偏移和断线重连。

它不是 RealSense SDK 驱动，不发布 D435i 深度/IMU，也不执行图像校正。D435i 主链路应使用 `realsense2_camera`；使用本包原始图建图时，需另行完成标定、TF 和校正。

## 入口和默认值

入口：`stereo_v4l2_camera.launch.py`；执行文件：`stereo_v4l2_direct_node`。

| 参数 | launch 默认值 | 含义 |
| --- | --- | --- |
| `video_device` | `/dev/v4l/by-id/usb-USB_Camera_USB_Camera_01.00.00-video-index0` | 改为实际 V4L2 设备 |
| `image_width`、`image_height` | 1280、480 | 拼接图尺寸；每眼 640×480 |
| `pixel_format`、`framerate` | YUYV、15 | 设备格式和请求采集帧率 |
| `publish_framerate` | 0 | 不另外限制发布帧率 |
| `swap_left_right` | true | 默认互换左右半幅 |
| `reliable_qos`、`qos_depth` | false、4 | 默认 Best Effort |
| `left_image_topic`、`right_image_topic` | `/cam0/image_raw`、`/cam1/image_raw` | 原始图 |
| `left_info_topic`、`right_info_topic` | `/cam0/camera_info`、`/cam1/camera_info` | 内参 |
| `left_frame_id`、`right_frame_id` | cam0、cam1 | 光学 frame 须与实际 TF 对齐 |
| `left_camera_info_file`、`right_camera_info_file` | 空 | 不提供有效文件时发布未标定 CameraInfo |
| `camera_time_offset_ms` | 0.0 | 时间戳校正，毫秒 |

完整相机控制参数以 launch 声明为准；不是每种设备都支持全部控制项。

## 构建和使用

按 [公共构建说明](../../README.md) 选择 `stereo_v4l2_camera`，需要 OpenCV、yaml-cpp 和 ROS 消息依赖。加载安装环境后：

```bash
ros2 launch stereo_v4l2_camera stereo_v4l2_camera.launch.py \
  video_device:=/dev/video0 \
  left_camera_info_file:=/absolute/path/left.yaml \
  right_camera_info_file:=/absolute/path/right.yaml
```

需核对实际设备、左右图顺序、标定分辨率、CameraInfo 的 K/D/R/P 和双目基线；只把话题改名为 `image_rect_raw` 不会让原始图变成校正图。当前包不发布相机静态 TF。
