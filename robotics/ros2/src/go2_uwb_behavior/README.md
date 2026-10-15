# RK/Lite3 UWB 按需行为控制

本包为上层提供 **3 个全局互斥的 ROS 2 Action** 和一个模式 Service，默认 IDLE：

| 接口 | 功能 |
| --- | --- |
| `/motion/follow_uwb`，`FollowUwb` | 持续跟随，直到取消或超时；timeout=0 不设总时限 |
| `/motion/random_roam`，`RandomRoam` | 冻结调用时 UWB 中心，在指定圆环内走到一个随机目标后结束 |
| `/motion/orbit_uwb_once`，`OrbitUwbOnce` | 接近 UWB 目标并顺/逆时针环绕一周后结束 |
| `/motion/set_behavior`，`SetBehavior` | 仅接受 IDLE=0、STOP=2；STOP 锁存本控制器并拒绝新 Goal |

完整字段、数字枚举及终态判断见 [上层接口](docs/UPSTREAM_API.md)；环绕客户端见 [OrbitUwbOnce 说明](docs/OrbitUwbOnce上层调用说明.md)；环境与验收见 [部署说明](docs/上层对接与部署.md)。

## 控制链路

```text
uwb_behavior_controller_node
  → /go2_uwb_local_follow/nominal_cmd
  → local_velocity_planner_node（自研 MPPI）
  → /go2_uwb_behavior/planner_cmd_vel
  → uwb_behavior_controller_node（输入新鲜度、模式与运动门控）
  → /cmd_vel
```

统一 launch 启动行为节点、UWB 适配、双目视差、障碍投影、滚动地图和局部规划器，不启动 UWB 硬件、RealSense 或底盘桥接。不要再同时启动旧 `local_follow.launch.py` 或直接输出底盘速度的单独跟随/规划入口。

## 构建与启动

按 [公共构建说明](../../README.md) 编译 `uwb_aoa_pkg`、`go2_uwb_local_follow` 和本包，加载同一安装环境。先准备厂家 UWB 消息、校正双目、`/leg_odom2` 和相机到 `base_footprint` 的 TF。

首次只检查接口和感知：

```bash
ros2 launch go2_uwb_behavior behavior_follow_roam.launch.py \
  enable_motion:=false cmd_vel_topic:=/cmd_vel
```

**launch 的 enable_motion 默认是 true。** false 时本控制器只输出零速度，但不会阻止其他节点控制底盘。实际运动应在部署层明确控制权后显式选择 true。

## 按需计算与空闲输出

Action 接受后发布 transient-local 门控 `/go2_uwb_behavior/compute_enable=true`。投影节点按门控订阅视差；没有视差输出订阅者时，支持惰性计算的上游节点可跳过匹配。RViz、rosbag 等额外订阅者会改变这一条件，不能只凭图像订阅仍存在判断 CPU 负载。

Follow/Orbit 进入最终停车流程时关闭门控；RandomRoam 在完成停车流程、结束 Action 时关闭。当前 YAML 设置 `publish_idle_velocity=false`：空闲时不以 20 Hz 持续发零；上一条非零命令归零时补发零，活动 Action 期间仍按控制频率发布。节点仍可能显示为 `/cmd_vel` 的 publisher。

本包没有跨 Nav2/遥控/动作执行器的通用速度仲裁器，也没有通过检测 Nav2 启动来自动互锁。STOP 仅约束本节点。活动期间由上层保证最终非零速度只有一个控制来源。

## 停车与验证

停车确认要求新鲜里程计；低 twist 或位姿稳定满足任一路证据并累计 0.30 秒，等待上限 2 秒。成功的一次性任务如果未确认停车会转为 `STOP_UNCONFIRMED`；取消/失败超时时保留原结果码，**CANCELED 本身不能证明实际停稳**。上层应等待 Result，并按需要核对底盘与里程计状态；Service/cancel ACK 不等于终态。

核对接口可用 `ros2 interface show go2_uwb_behavior/action/OrbitUwbOnce` 等命令；测试命令的输出目录用 [公共构建说明](../../README.md) 中的 colcon 参数。文档历史 CPU/帧率数字不作为当前 RK3588 的性能保证，本次没有运行相机或运动验收。
