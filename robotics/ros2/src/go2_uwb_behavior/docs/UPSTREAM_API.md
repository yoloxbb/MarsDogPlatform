# RK/Lite3 UWB 行为上层调用接口

核对日期：2026-10-11。接口定义见本包 `action/`、`srv/`；下表范围是当前 `behavior_controller.yaml` 的配置值，修改服务端配置后以实际值为准。

## 1. 接口选择与互斥

| 意图 | 接口与类型 | 生命周期 |
| --- | --- | --- |
| 跟着我 | `/go2/follow_uwb`，`go2_uwb_behavior/action/FollowUwb` | 持续到取消或超时 |
| 原地玩耍 | `/go2/random_roam`，`go2_uwb_behavior/action/RandomRoam` | 单次随机目标到达并停车后结束 |
| 围着我转一圈 | `/go2/orbit_uwb_once`，`go2_uwb_behavior/action/OrbitUwbOnce` | 接近、环绕一周、停车后结束 |
| 停止/解除 | `/go2/set_behavior`，`go2_uwb_behavior/srv/SetBehavior` | STOP=2 / IDLE=0 |

三个 Action 全局互斥，不自动抢占已有 Goal。STOP 锁存时拒绝新 Goal。上层保存 Goal Handle，先取消当前任务、等待 Result，再决定后续行为。语音识别层只调用任务接口，速度控制权由任务/部署层协调。

所有 Feedback `state` 和 Result `code` 都是 **uint8 数字枚举**，不是字符串。应使用生成接口的常量比较；不要用诊断消息中的文字状态替代它们。

## 2. FollowUwb

Goal：`float64 timeout_sec`，0 表示不设总时限；显式值 5～3600 秒。非有限值、负值和范围外值拒绝。

```bash
ros2 action send_goal /go2/follow_uwb \
  go2_uwb_behavior/action/FollowUwb "{timeout_sec: 0.0}" --feedback
```

Feedback：`state`、`distance`（米）、`heading`（弧度）、`elapsed_sec`（秒）。state 为 STARTING=0、FOLLOWING=1、HOLDING=2、INPUT_PAUSED=3、STOPPING=4。

Result：`code`、`message`、`elapsed_sec`、`final_distance`。

| code | 常量 | 含义 |
| --- | --- | --- |
| 0 | SUCCESS | 成功 |
| 1 | CANCELED | 上层取消 |
| 2 | PREEMPTED_BY_MODE | IDLE/STOP 请求抢占 |
| 3 | NOT_READY | 就绪窗口内输入未备齐 |
| 4 | TIMEOUT | 总时限到达 |
| 5 | INPUT_TIMEOUT | 输入恢复窗口到达仍未恢复 |
| 6 | STOP_UNCONFIRMED | 成功停车流程无法确认停稳 |

跟随是持续任务，正常“别跟了”通过 cancel 请求完成，期待 `STATUS_CANCELED` + CANCELED；停车证据限制见第 5 节。

## 3. RandomRoam

| Goal 字段 | 类型 | 当前配置下规则 |
| --- | --- | --- |
| `random_seed` | uint32 | 0 使用随机种子；非零便于复现 |
| `timeout_sec` | float64 | 0 使用默认 30 秒；显式值 5～120 秒 |
| `min_radius` | float64 | 目标距冻结中心的最小半径，米 |
| `max_radius` | float64 | 最大半径，米 |

半径同时为 0 时使用默认 0.5～2.0 米；否则需为有限值且 `0.5 <= min_radius < max_radius <= 2.0`。

```bash
ros2 action send_goal /go2/random_roam \
  go2_uwb_behavior/action/RandomRoam \
  "{random_seed: 0, timeout_sec: 30.0, min_radius: 0.5, max_radius: 2.0}" --feedback
```

优先在 Goal 接受时冻结过滤后的 UWB odom 坐标；样本不足时在输入首次就绪后冻结。目标在圆环中按面积均匀采样并检查障碍净空。后续 UWB 移动不拖动本次目标和围栏中心；这是单次任务，不是持续漫游。当前配置还保留 5.0 米软返回触发、4.5 米释放、5.6 米限制区和 6.0 米绝对围栏。

Feedback：`state`、`target_pose`、`distance_remaining`、`owner_distance`、`elapsed_sec`。state 为 PREPARING=0、SELECTING_GOAL=1、NAVIGATING=2、RETURNING=3、STOPPING=4、RETRYING=5。

Result：`code`、`message`、`reached_pose`、`center_pose`、`target_pose`、`owner_distance`、`min_clearance`。Pose 使用 odom；距离/净空单位米。

| code | 常量 |
| --- | --- |
| 0 | SUCCESS |
| 1 | CANCELED |
| 2 | PREEMPTED_BY_MODE |
| 3 | NOT_READY |
| 4 | NO_VALID_GOAL |
| 5 | BLOCKED |
| 6 | TIMEOUT |
| 7 | INPUT_TIMEOUT |
| 8 | GEOFENCE_STOP |
| 9 | STOP_UNCONFIRMED |

后续依赖任务成功的动作只接受 `STATUS_SUCCEEDED` 且 `result.code == RandomRoam.Result.SUCCESS`。

## 4. OrbitUwbOnce

| Goal 字段 | 类型 | 当前配置下规则 |
| --- | --- | --- |
| `timeout_sec` | float64 | 0 使用 60 秒；显式值 5～180 秒 |
| `orbit_radius` | float64 | 0 使用 1.0 米；显式值 0.5～2.0 米 |
| `direction` | int8 | 0 或 1 逆时针；-1 顺时针；其他值拒绝 |

```bash
ros2 action send_goal /go2/orbit_uwb_once \
  go2_uwb_behavior/action/OrbitUwbOnce \
  "{timeout_sec: 60.0, orbit_radius: 1.0, direction: 0}" --feedback
```

Feedback：`state`、`distance`、`orbit_angle`、`elapsed_sec`；state 为 STARTING=0、APPROACHING=1、ORBITING=2、INPUT_PAUSED=3、STOPPING=4。角度单位弧度。

Result：`code`、`message`、`elapsed_sec`、`final_distance`、`completed_angle`。

| code | 常量 |
| --- | --- |
| 0 | SUCCESS |
| 1 | CANCELED |
| 2 | PREEMPTED_BY_MODE |
| 3 | NOT_READY |
| 4 | TIMEOUT |
| 5 | INPUT_TIMEOUT |
| 6 | BLOCKED |
| 7 | STOP_UNCONFIRMED |

完成判断为 `STATUS_SUCCEEDED` + SUCCESS，不能只看反馈角度达到约 2π。Python 调用见 [环绕接口说明](OrbitUwbOnce上层调用说明.md)。

## 5. 模式、取消与停车证据

SetBehavior 只接受 IDLE=0 和 STOP=2；FOLLOW=1、ROAM=3 被拒绝。活动任务遇到模式请求时进入停车流程，Service 的 `accepted=true` 仅表示受理，`current_mode` 可能仍是旧模式。

```bash
ros2 service call /go2/set_behavior go2_uwb_behavior/srv/SetBehavior "{mode: 2}"
ros2 service call /go2/set_behavior go2_uwb_behavior/srv/SetBehavior "{mode: 0}"
```

cancel 也是异步受理；上层需等待原 Goal 的最终 Result。停车确认要求新鲜 odom，低 twist（线速度绝对值不大于 0.04 m/s、角速度绝对值不大于 0.08 rad/s）或位姿稳定（平移 0.02 m、偏航 0.03 rad 容差）满足任一路证据，累计 0.30 秒。最多等待 2 秒。

**当前实现只把原拟成功的任务在停车确认超时时改为 STOP_UNCONFIRMED；取消或失败会保留原 CANCELED/错误码并结束。** 因此收到 CANCELED 不代表物理停车已经被确认。需要以停稳为前提的后续任务还需核对底盘/新鲜里程计；本次只修正文档，没有修改此实现。

STOP 仅锁存本 UWB 控制器，不能自动阻断其他节点或遥控器。本包也没有检测 Nav2 启动的自动互锁。上层必须协调控制权。

## 6. 输入、门控与默认时限

| 数据 | 默认来源 |
| --- | --- |
| 厂家 UWB | `/libAoa_robot_publisher`，适配后 `/uwb/target_point` |
| 底盘位姿与速度 | `/leg_odom2`，nav_msgs/Odometry |
| 双目 | `/camera/camera/infra1/image_rect_raw`、`/camera/camera/infra2/image_rect_raw` 及 CameraInfo |
| 障碍 | `/local_rolling_obstacle`，来自本包统一链路 |
| TF | 相机到 base_footprint，及一致的 odom 位姿 |

当前配置就绪窗口 2 秒、输入恢复窗口 3 秒；输入短时中断先停车，恢复后按当前任务状态继续。不同模式检查其所需输入，漫游中心冻结后不随实时 UWB 移动。

门控是 transient-local `/go2_uwb_behavior/compute_enable`：Action 接受开启；Follow/Orbit 进入最终停车时关闭，RandomRoam 结束时关闭。当前配置 `publish_idle_velocity=false`，IDLE/STOP 不持续发零。详细环境加载与分阶段验收见 [部署说明](上层对接与部署.md)。
