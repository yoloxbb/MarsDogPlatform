# 上层 bbox 单次人体定位接口说明

## 1. 功能边界

`person_3d_localization` 不运行 YOLO，也不直接调用 Nav2。它完成一次请求、一次计算、
一次响应：

```text
上层保留检测图像 Header
        ↓
上层运行 YOLO 并选定一个人体 bbox
        ↓
调用 /person_3d_localization/locate_from_bbox
        ↓
本节点匹配同一时刻的对齐深度图和 CameraInfo
        ↓
bbox 深度过滤 → 相机三维均值点 → TF 转换到 map
        ↓
返回人体点和保留安全距离的固定导航目标
        ↓
上层决定是否发送一次 NavigateToPose
```

每次服务请求只处理一个 bbox。多人场景下，由上层先选择要跟随的人，再传入该人的
bbox。本节点不进行人体 ID 关联、连续跟踪或目标更新。

## 2. 通信接口总览

| 方向 | 名称 | ROS 2 类型 | 用途 |
|---|---|---|---|
| 上层 → 本节点 | `/person_3d_localization/locate_from_bbox` | `person_3d_localization/srv/LocateFromBbox` | 提交一次 bbox 定位请求 |
| 相机 → 本节点 | `/camera/camera/aligned_depth_to_color/image_raw` | `sensor_msgs/msg/Image` | 对齐到检测图像的深度图 |
| 相机 → 本节点 | `/camera/camera/color/camera_info` | `sensor_msgs/msg/CameraInfo` | 检测图像对应的相机内参 |
| 本节点 → 调试 | `/person_3d_localization/person_point` | `geometry_msgs/msg/PointStamped` | 成功定位后的人体三维均值点 |
| 本节点 → 调试 | `/person_3d_localization/navigation_goal` | `geometry_msgs/msg/PoseStamped` | 成功计算后的固定导航目标 |
| 上层 → Nav2 | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | 上层按需发送一次导航目标 |

服务名称和所有话题都可以在参数文件中修改。深度图和 CameraInfo 使用
`SensorDataQoS`；服务使用 ROS 2 请求/响应机制。

## 3. 上层必须提供的数据

服务定义：

```text
std_msgs/Header image_header
sensor_msgs/RegionOfInterest bbox
float32 stand_off_distance
---
bool success
bool navigation_required
uint8 status
string message
geometry_msgs/PointStamped person_point
geometry_msgs/PoseStamped navigation_goal
float32 valid_depth_ratio
float32 mean_depth
float32 depth_stddev
```

### 3.1 `image_header`

必须使用产生该 bbox 的原始相机图像 Header，尤其是原始时间戳：

| 字段 | 要求 |
|---|---|
| `image_header.stamp` | 复制检测输入图像的原始时间戳，不能填写服务调用时刻 |
| `image_header.frame_id` | 建议复制检测输入图像的 frame，默认通常为 `camera_color_optical_frame` |

YOLO 推理结束后，深度相机可能已经发布了后续帧。本节点缓存最近的深度帧，并使用
`image_header.stamp` 找到和 bbox 对应的那一帧，而不是直接使用收到请求时的最新深度。

默认允许的图像与深度时间差为 `0.05 s`。缓存长度为 60 帧，30 Hz 时约覆盖 2 秒。
如果上层推理和调度延迟超过缓存覆盖时间，需要增大 `cache_size`。

零时间戳只用于人工调试：节点会选择最新且不超过 `max_latest_depth_age` 的深度帧。
正式上层程序不得依赖零时间戳。

### 3.2 `bbox`

类型为 `sensor_msgs/msg/RegionOfInterest`：

| 字段 | 单位 | 含义 |
|---|---:|---|
| `x_offset` | pixel | bbox 左上角横坐标 |
| `y_offset` | pixel | bbox 左上角纵坐标 |
| `width` | pixel | bbox 宽度，必须大于 0 |
| `height` | pixel | bbox 高度，必须大于 0 |
| `do_rectify` | — | 当前实现不使用，填写 `false` |

bbox 坐标必须满足以下要求：

1. 已经从 YOLO 网络输入尺寸还原到原始检测图像尺寸；
2. 已经撤销 letterbox padding；
3. 与配置的深度图处于同一个像素坐标系；
4. D435i 默认配置要求 bbox 来自彩色图，深度为 aligned-to-color 深度；
5. 坐标使用左上角为原点，`u` 向右、`v` 向下。

例如，YOLO 在 `640×640` letterbox 图上给出的 bbox，不能直接用于一幅
`640×480` 原图。上层必须先撤销上下 padding，恢复到 `640×480` 坐标。

### 3.3 `stand_off_distance`

导航目标与人体之间的安全距离，单位为米：

- 大于 `0`：使用本次请求值；
- 小于或等于 `0`：使用节点参数 `default_stand_off_distance`；
- 默认值：`1.5 m`。

目标点在 `map` 平面内按以下关系计算：

```text
direction = normalize(person_xy - robot_xy)
goal_xy = person_xy - stand_off_distance × direction
goal_yaw = 朝向 person_xy
```

## 4. 请求示例

### 4.1 命令行请求

正式请求应使用检测图像的真实时间戳：

```bash
ros2 service call /person_3d_localization/locate_from_bbox \
  person_3d_localization/srv/LocateFromBbox \
  "{image_header: {
       stamp: {sec: 1789700000, nanosec: 123456789},
       frame_id: 'camera_color_optical_frame'},
     bbox: {
       x_offset: 210,
       y_offset: 90,
       width: 170,
       height: 320,
       do_rectify: false},
     stand_off_distance: 1.5}"
```

零时间戳调试请求：

```bash
ros2 service call /person_3d_localization/locate_from_bbox \
  person_3d_localization/srv/LocateFromBbox \
  "{image_header: {stamp: {sec: 0, nanosec: 0}, frame_id: ''},
     bbox: {x_offset: 210, y_offset: 90, width: 170, height: 320, do_rectify: false},
     stand_off_distance: 1.5}"
```

### 4.2 Python 上层请求

```python
from person_3d_localization.srv import LocateFromBbox

# image_msg 是送入 YOLO 的原始 ROS 图像消息，bbox 坐标已还原到它的分辨率。
request = LocateFromBbox.Request()
request.image_header = image_msg.header
request.bbox.x_offset = int(x1)
request.bbox.y_offset = int(y1)
request.bbox.width = int(x2 - x1)
request.bbox.height = int(y2 - y1)
request.bbox.do_rectify = False
request.stand_off_distance = 1.5

client = node.create_client(
    LocateFromBbox,
    '/person_3d_localization/locate_from_bbox',
)
future = client.call_async(request)
```

处理异步响应时必须先判断 `success`：

```python
response = future.result()
if not response.success:
    node.get_logger().error(
        f'人体定位失败: status={response.status}, message={response.message}'
    )
elif not response.navigation_required:
    node.get_logger().info('机器人已经位于安全距离内，不发送导航目标')
else:
    nav_goal = response.navigation_goal
    # 将 nav_goal 作为一次 NavigateToPose.Goal.pose 发送给现有 Nav2。
```

### 4.3 C++ 上层请求

```cpp
auto request = std::make_shared<person_3d_localization::srv::LocateFromBbox::Request>();
// 必须保留产生 bbox 的原图时间戳。
request->image_header = image_message->header;
request->bbox.x_offset = static_cast<uint32_t>(x1);
request->bbox.y_offset = static_cast<uint32_t>(y1);
request->bbox.width = static_cast<uint32_t>(x2 - x1);
request->bbox.height = static_cast<uint32_t>(y2 - y1);
request->bbox.do_rectify = false;
request->stand_off_distance = 1.5F;

auto future = locate_client->async_send_request(request);
```

## 5. 本节点返回的数据

### 5.1 通用状态字段

| 字段 | 含义 |
|---|---|
| `success` | 整次定位和目标计算是否成功 |
| `navigation_required` | 是否需要把 `navigation_goal` 发送给 Nav2 |
| `status` | 结构化状态码 |
| `message` | 中文状态说明，主要用于日志和调试 |

上层处理规则：

```text
success == false
    丢弃 person_point 和 navigation_goal，根据 status 处理错误

success == true && navigation_required == false
    人体定位成功，但机器人已经在安全距离内，不发送平移导航目标

success == true && navigation_required == true
    将 navigation_goal 发送一次给 NavigateToPose
```

### 5.2 `person_point`

`geometry_msgs/msg/PointStamped`，表示 bbox 内稳健深度点反投影后的三维均值：

- `header.frame_id`：默认是 `map`；由参数 `target_frame` 决定；
- `header.stamp`：匹配到的深度测量时间戳；
- `point.x/y/z`：人体均值点在目标坐标系中的位置，单位为米。

该点通常接近人体躯干区域的三维均值，不是人体脚底点。导航只使用它的平面 `x/y`。

### 5.3 `navigation_goal`

`geometry_msgs/msg/PoseStamped`，可以直接赋给 `NavigateToPose.Goal.pose`：

- `header.frame_id`：默认是 `map`；
- `header.stamp`：目标生成时刻；
- `pose.position.x/y`：与人体保持安全距离的固定目标点；
- `pose.position.z`：固定为 `0`；
- `pose.orientation`：使机器人朝向人体的四元数。

当 `navigation_required=false` 时，目标位置会填写为测量时刻机器人自身位置。上层默认
不应发送该目标；如果产品逻辑希望机器人原地朝向人体，可以自行决定是否使用其朝向。

### 5.4 深度质量字段

| 字段 | 单位 | 含义 |
|---|---:|---|
| `valid_depth_ratio` | 0～1 | bbox 中央采样区域经深度过滤后保留的比例 |
| `mean_depth` | m | 内点在相机光轴方向上的平均深度 Z |
| `depth_stddev` | m | 内点深度标准差，越小通常越稳定 |

`mean_depth` 是相机光学坐标系的 Z，不是人体到机器人的平面欧氏距离。

## 6. 状态码

| 数值 | 常量 | 含义 | 上层建议 |
|---:|---|---|---|
| 0 | `STATUS_OK` | 成功 | 根据 `navigation_required` 决定是否导航 |
| 1 | `STATUS_NO_DEPTH` | 没收到深度，或缓存中没有匹配时间戳的深度 | 检查 aligned depth 和时间戳，必要时稍后重试 |
| 2 | `STATUS_NO_CAMERA_INFO` | 没有匹配内参，或内参与深度分辨率不一致 | 检查 CameraInfo 话题和相机 profile |
| 3 | `STATUS_INVALID_BBOX` | bbox 为空或完全越界 | 检查 bbox 还原和裁剪逻辑 |
| 4 | `STATUS_INVALID_DEPTH` | 有效深度不足、离群过滤后点不足或几何结果异常 | 不导航，可重新检测或提示失败 |
| 5 | `STATUS_TF_UNAVAILABLE` | 测量时刻无法转换到目标坐标系 | 检查 TF 链和时间同步 |
| 6 | `STATUS_INVALID_REQUEST` | 安全距离、frame 或其他请求数据非法 | 修正上层请求 |

失败响应中的点和目标保持默认值，上层不得在 `success=false` 时使用它们。

## 7. TF 与坐标系要求

默认参数：

```yaml
target_frame: map
robot_frame: base_footprint
```

运行时必须存在测量时刻的完整 TF 链：

```text
map → odom → base_footprint → camera_color_optical_frame
```

节点使用深度图的 `header.frame_id` 作为三维点源坐标系，并使用深度测量时间戳查询 TF。
它不会使用“最新 TF”替代历史测量时刻的 TF。

## 8. 发送给 Nav2

上层只在以下条件同时满足时发送导航：

```text
response.success == true
response.navigation_required == true
response.navigation_goal.header.frame_id == "map"
```

Python 侧核心映射关系：

```python
from nav2_msgs.action import NavigateToPose

goal = NavigateToPose.Goal()
goal.pose = response.navigation_goal
nav_action_client.send_goal_async(goal)
```

这是一次固定目标导航。本节点不会继续更新目标；当前普通
`robot_slam_bringup/nav.launch.py` 和 `navigate_to_pose_no_backup.xml` 可以直接处理。

## 9. 启动和联调检查

启动节点：

```bash
source /opt/ros/humble/setup.bash
source /home/bird/robot_ws_leg_velocity/slam_ws/install/setup.bash
ros2 launch person_3d_localization person_3d_localization.launch.py
```

调用服务前依次检查：

```bash
ros2 topic hz /camera/camera/aligned_depth_to_color/image_raw
ros2 topic hz /camera/camera/color/camera_info
ros2 topic echo /camera/camera/aligned_depth_to_color/image_raw --once --field header
ros2 service type /person_3d_localization/locate_from_bbox
ros2 run tf2_ros tf2_echo map camera_color_optical_frame
ros2 run tf2_ros tf2_echo map base_footprint
```

期望的服务类型：

```text
person_3d_localization/srv/LocateFromBbox
```

成功调用后还可以在 RViz 或命令行检查：

```bash
ros2 topic echo /person_3d_localization/person_point --once
ros2 topic echo /person_3d_localization/navigation_goal --once
```

## 10. 默认参数摘要

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `default_stand_off_distance` | 1.5 | 默认人体安全距离，米 |
| `arrival_tolerance` | 0.15 | 已处于安全距离的附加容差，米 |
| `cache_size` | 60 | 深度和 CameraInfo 缓存帧数 |
| `max_timestamp_difference` | 0.05 | bbox 图像与深度最大时间差，秒 |
| `depth_min` | 0.3 | 最小有效深度，米 |
| `depth_max` | 6.0 | 最大有效深度，米 |
| `bbox_width_scale` | 0.6 | bbox 中央采样区域宽度比例 |
| `bbox_height_scale` | 0.7 | bbox 中央采样区域高度比例 |
| `min_valid_depth_ratio` | 0.20 | 最低有效深度比例 |
| `tf_timeout` | 0.3 | 单次 TF 查询超时，秒 |

修改默认参数请编辑 `config/person_3d_localization.yaml`，或通过自定义参数文件启动。
