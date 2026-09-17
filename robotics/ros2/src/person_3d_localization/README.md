# person_3d_localization

接收上层给出的单个人体 bbox，从与原图时间戳匹配的对齐深度图中提取稳健三维均值点，
然后在 `map` 坐标系中生成保留安全距离的固定 Nav2 目标。包内不包含 YOLO、人体跟踪或
Nav2 action client。

## 数据约束

- bbox 必须是 YOLO 缩放和 letterbox 还原后的原图坐标。
- bbox 所属图像必须与 `depth_topic` 使用同一像素坐标系；D435i 推荐使用对齐到彩色图的深度。
- 请求应携带 bbox 原图的时间戳。零时间戳仅用于人工测试，会选择最新且未过期的深度帧。
- `16UC1` 深度默认按毫米解释，比例由 `depth_16u_scale` 控制；`32FC1` 按米解释。

## 构建与启动

```bash
source /opt/ros/humble/setup.bash
cd ~/robot_ws_leg_velocity/slam_ws
colcon build --packages-select person_3d_localization --symlink-install
source install/setup.bash
ros2 launch person_3d_localization person_3d_localization.launch.py
```

D435i 必须发布与 bbox 图像对齐的深度，例如默认配置使用：

```text
/camera/camera/aligned_depth_to_color/image_raw
/camera/camera/color/camera_info
```

## 服务

服务名称：`/person_3d_localization/locate_from_bbox`

上层传入 bbox、原图时间戳和可选安全距离。`stand_off_distance <= 0` 时使用参数中的
`default_stand_off_distance`。成功响应包含人体 `person_point` 和固定导航目标
`navigation_goal`；上层只需把后者作为一次 `NavigateToPose` action 目标发送给现有 Nav2。

人工测试可使用零时间戳选取最新深度：

```bash
ros2 service call /person_3d_localization/locate_from_bbox \
  person_3d_localization/srv/LocateFromBbox \
  "{image_header: {frame_id: '', stamp: {sec: 0, nanosec: 0}}, \
    bbox: {x_offset: 200, y_offset: 100, width: 180, height: 300, do_rectify: false}, \
    stand_off_distance: 1.5}"
```

调试输出：

- `/person_3d_localization/person_point`
- `/person_3d_localization/navigation_goal`

现有 `robot_slam_bringup/nav.launch.py` 和固定目标行为树无需修改。
