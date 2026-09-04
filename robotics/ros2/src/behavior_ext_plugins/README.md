# FollowPath 恢复行为树与空闲方向脱困

该包包含两个配套组件：

1. `nav2_behaviors/BackUpTwzFree`：`nav2_core::Behavior` 插件，从配置的局部或全局 costmap 中寻找自由栅格方向并执行移动。
2. `follow_path_recovery_bt_node`：订阅路径并执行 `RecoveryNode(FollowPath, BackUp)` 的行为树。控制失败后调用标准 `/backup` action，恢复成功后重试最新路径。

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
cd ~/go2_follow
colcon build --symlink-install --packages-select behavior_ext_plugins
source install/setup.bash
```

该执行器已由 DWB、直连 MPPI、Dynamic A*+MPPI 和 TEB launch 自动启动，一般无需单独运行。
