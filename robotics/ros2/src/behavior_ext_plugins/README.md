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

## 统一导航的起点占用脱困门限

统一入口新增 IsStartOccupied 和 HasValidPath 条件：仅当新鲜全局 costmap 中机器人中心格为 253/254 时允许移动脱困；自由、普通膨胀区、未知、图外、过期地图或缺失 TF 不允许。HasValidPath 阻止规划失败后的空路径进入控制器。behavior server 的 require_start_occupied=true 提供相同检查，直接调用 backup action 也不能绕过。该开关默认 false，保留其他历史入口行为；统一入口设置地图最大年龄 5 s。门限判断地图起点占用，不证明真实定位一定错误。

## 清图后的观测与地图等待

统一导航树使用同一 BT 动态库中的 `WaitForFreshCostmap` 替代固定 1 s 等待。清图服务成功返回后才开始等待；移动脱困成功后也执行相同等待，然后才能重新规划。等待放在 `RoundRobin` 外，超时返回失败并结束本次导航恢复，不会因超时切换到移动脱困。

放行需要依次观察到：至少一路 `/local_grid_obstacle` 或 `/local_grid_ground` 的源时间戳晚于本次等待起点；之后局部地图 `published_footprint` 的新时间戳表明完成一次地图更新；之后收到完整的 `local_costmap/costmap_raw` 快照，并且观测坐标到地图坐标的 TF 可用。旧数据、未来时间戳、无效地图和上一轮恢复的数据不能复用。RTAB-Map 省略为空的点云类别，因此不要求两路同时发布；真正发布的有效空点云也可接受。

```yaml
bt_navigator:
  ros__parameters:
    recovery_observation_timeout: 5.0
    recovery_observation_topics: ["/local_grid_obstacle", "/local_grid_ground"]
    recovery_fresh_costmap_topic: local_costmap/costmap_raw
    recovery_costmap_update_topic: local_costmap/published_footprint
```

超时使用单调时钟，ROS 时间停住也会退出；取消会清理本轮状态。5 s 只计算动作成功后的数据等待，不包含原清图服务和移动动作本身的时限。每次新恢复都重新获取观测。超时日志列出收到的观测和是否观察到地图更新。

此检查利用当前 Nav2 Humble 的更新完成事件和发布时间顺序，不是 STVL 对某一帧点云逐点处理的确认接口，也不是定位正确性判据。全局地图没有清空，此处等待的是局部代价地图。独立示例执行器的历史行为树未改。
