# FollowPath 恢复行为树与空闲方向脱困

该包包含两个配套组件：

1. `nav2_behaviors/BackUpTwzFree`：`nav2_core::Behavior` 插件，从配置的局部或全局 costmap 中寻找自由栅格方向并执行移动。
2. `follow_path_recovery_bt_node`：订阅路径并执行 `RecoveryNode(FollowPath, BackUp)` 的行为树。控制失败后调用标准 `backup` action，恢复成功后重试最新路径。路径、状态及 action 名均为可配置的相对名称，可随 ROS namespace 自动解析。

行为树文件：`behavior_trees/follow_path_with_free_space_recovery.xml`。

## 行为树结构

```xml
<RecoveryNode number_of_retries="{recovery_retries}">
  <FollowPath path="{path}" controller_id="{controller_id}"/>
  <BackUp backup_dist="{recovery_distance_m}"
          backup_speed="{recovery_speed_mps}"/>
</RecoveryNode>
```

`BackUp` 是 Nav2 标准 BT 节点；只有 behavior server 中的实现被替换为空闲方向插件：

```yaml
behavior_server:
  ros__parameters:
    behavior_plugins: [backup]
    backup:
      plugin: nav2_behaviors/BackUpTwzFree
    global_frame: odom
    robot_base_frame: base_footprint
    min_recovery_distance: 0.15
    max_recovery_distance: 1.0
    recovery_time_margin: 1.5
    search_costmap_topic: global_costmap/costmap_raw
    service_name: global_costmap/get_costmap
    enable_strafe: true
```

插件优先使用 `search_costmap_topic` 持续缓存的完整代价地图，话题尚无数据时才调用 `service_name`。它会扫描机器人半径外、`max_radius` 内且代价不高于阈值的栅格，计算满足最小自由格数量的近邻区域质心，并在 `min_recovery_distance` 到 `max_recovery_distance` 范围内动态设置本次移动距离。全向模式可发布 `linear.y`，碰撞前瞻会同时预测纵向和横向运动；候选格不足或质心无法给出明确方向时按最小距离固定向后。碰撞前瞻失败、超时或达到移动距离时立即停止。

## 编译

```bash
source /opt/ros/humble/setup.bash
export MARS_ROOT=/home/marsdog/MarsDogPlatform
export ROBOTICS_OUT="$MARS_ROOT/out/rk3588-robotics"
export CMAKE_BUILD_PARALLEL_LEVEL=2
export MAKEFLAGS=-j2
colcon --log-base "$ROBOTICS_OUT/log" build \
  --base-paths "$MARS_ROOT/robotics/ros2/src" \
  --build-base "$ROBOTICS_OUT/build" --install-base "$ROBOTICS_OUT/install" \
  --symlink-install --executor sequential --packages-select behavior_ext_plugins \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
source "$ROBOTICS_OUT/install/local_setup.bash"
```

构建前须具备 Nav2 开发依赖和 BehaviorTree.CPP v3，详见 [公共构建说明](../../README.md)。本包没有自带 launch。

当前 `robot_slam_bringup/config/nav.yaml` 将 Nav2 behavior server 的 `backup` 实现配置为本包插件，其导航行为树通过标准 `BackUp` 调用它。这条主链路不额外启动 `follow_path_recovery_bt_node`。

独立执行器供外部路径控制管线使用，可运行 `ros2 run behavior_ext_plugins follow_path_recovery_bt_node`。默认路径话题 `follow_path`、状态话题 `follow/recovery_status`、Action 名 `follow_path` 和 `backup`，支持 namespace；运行前准备对应 Nav2 Action server，避免与常规 NavigateToPose 同时争用控制。旧文档提到的 DWB/TEB/Dynamic A* launch 不在本目录，不能据此假定当前主入口已自动启动独立执行器。
