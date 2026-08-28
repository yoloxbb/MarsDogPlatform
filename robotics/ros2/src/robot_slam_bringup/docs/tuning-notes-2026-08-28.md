# 调参记录：Nav2 全局重规划改造 + OpenVINS 里程计漂移排查

日期：2026-08-28
涉及包：`robot_slam_bringup`
环境：Jetson (aarch64) / ROS 2 Humble / `nav2 1.1.20` / GO2 + D435i

标注约定：
- **[已验证]** —— 通过读取本机源码、配置或执行命令确认过的事实
- **[待确认]** —— 需要在实机上实测才能定论
- **[推断]** —— 基于源码语义分析得出，未经实测

---

## 第一部分：让全局路径不再周期重规划（已实施）

### 需求

全局路径不要频繁重新规划，只在「目标变更」和「陷入恢复行为之后」重新规划；同时恢复行为不要清空全局代价地图。

### 关键认知：重规划频率不在 yaml 里

这是最容易走错的一步。**`planner_server` 的 `expected_planner_frequency` 完全不控制重规划频率。**

**[已验证]** 读 `nav2_planner/src/planner_server.cpp`（humble 分支）确认：该参数只在 configure 时换算成 `max_planner_duration_ = 1 / expected_planner_frequency`，然后在 `computePlan()` / `computePlanThroughPoses()` 里做一次耗时检查：

```cpp
if (max_planner_duration_ && cycle_duration.seconds() > max_planner_duration_) {
  RCLCPP_WARN(... "Planner loop missed its desired rate of %.4f Hz." ...)
}
```

**它只决定什么时候打印 WARN。** 设为 0 或负数会关闭该警告（源码里的提示信息还带着 `overrrun` 的拼写错误）。

真正的周期重规划来自行为树里的 `<RateController hz="0.5">` —— 每 2 秒无条件 tick 一次 `ComputePathToPose`。

### `IsPathValid` 的确切判定标准

方案设计阶段考虑过用 `IsPathValid` 做「路径被堵才重规划」的触发式方案。为此查清了它的判定逻辑。

**[已验证]** `nav2_planner 1.1.20` 的 `isPathValid` 服务实现：

| 行为 | 实现 |
|---|---|
| 空路径 | 判为**失效**（`request->path.poses.empty()` 时直接返回 false），因此不会死锁 |
| 起始检查点 | 遍历全部 pose 找出离机器人最近的一个，从它开始向后检查——刻意跳过已驶过、可能已被占据的点 |
| 检查范围 | 从最近点一直到**路径终点**（不是前方一小段） |
| 模式选择 | 由 `costmap_ros_->getUseRadius()` 决定 |
| radius 模式 | `LETHAL_OBSTACLE`(254) **或** `INSCRIBED_INFLATED_OBSTACLE`(253) 都算失效 |
| footprint 模式 | 用完整机身轮廓 `footprintCostAtPose`，**只有 `LETHAL_OBSTACLE`(254) 算失效** |
| `NO_INFORMATION`(255) | **从不被检测**，未知区域单独不会让路径失效 |
| 取不到机器人位姿 | 整段检查被跳过，路径保持「有效」 |

本项目的 `global_costmap` 配了 `footprint` 而非 `robot_radius`，所以走 **footprint 模式**：`inflation_radius: 0.8` 那整条膨胀带（cost 128~252）的任何变化都不会触发重规划，连内切膨胀 253 也不算。这个特性对「抗地图抖动」很有利。

### 最终采用的方案（严格版）

主分支彻底去掉 `RateController`，换成条件短路：

```xml
<Fallback name="ReplanOnlyOnGoalChange">
  <Inverter><GlobalUpdatedGoal/></Inverter>   <!-- 目标没变 → SUCCESS，短路 -->
  <Sequence name="ComputeAndSmoothPath"> ... </Sequence>
</Fallback>
```

**为什么首次规划有保证**：`GloballyUpdatedGoalCondition` 的 `first_time` 分支首次 tick 必返回 SUCCESS，经 `Inverter` 变 FAILURE，直接进入规划分支。

**为什么不再外套 `RateController`**：该条件只是黑板内存比较，按 `bt_loop_duration: 20ms` 评估反而让目标变更响应更快，而规划分支已被条件挡住，不会被反复触发。

恢复分支的两处改动：

1. 删掉 `ClearEntireCostmap ClearGlobalCostmap`，只保留清局部图
2. `RoundRobin` 后面串上 `ComputePathToPose` + `SmoothPath`

```xml
<Sequence name="RecoverThenReplan">
  <RoundRobin name="RecoveryActions"> ...三个恢复动作... </RoundRobin>
  <Sequence name="ReplanAndSmoothAfterRecovery">
    <Fallback><ComputePathToPose .../><AlwaysSuccess/></Fallback>
    <Fallback><SmoothPath .../><AlwaysSuccess/></Fallback>
  </Sequence>
</Sequence>
```

### 三个设计细节，都是踩过才知道的

**1. 恢复分支必须自己补一次 `SmoothPath`。**
主分支此后目标没变会一直短路，永远不会再平滑。如果恢复侧只规划不平滑，机器人会去跟一条未经 `constrained_smoother` 推离膨胀带的原始 A* 路径，贴墙风险显著上升。

**2. 恢复分支的规划失败必须用 `AlwaysSuccess` 吞掉。**
否则恢复动作被判定为失败，`RecoveryNode` 会直接结束整个导航，连后续的 `BackUp` / `DriveOnHeading` 都不会尝试。

**3. 把重规划提到 `RoundRobin` 外面依赖一个 BT.CPP 语义。** **[推断]**
`ControlNode::haltChild(i)` 只对 `status() == RUNNING` 的子节点调 `halt()`。`RoundRobinNode` 返回 SUCCESS 时自身状态是 SUCCESS，所以外层 `Sequence` 收尾的 `haltChildren()` 不会触发 `RoundRobinNode::halt()` 把 `current_child_idx_` 归零，轮换得以保留。

> **这是本次改动唯一未实测的假设。** 失效表现是 silent failure：恢复行为永远停在「清局部图」，从不轮到 `BackUp`。若观察到该现象，改成在 `RoundRobin` 每个分支末尾各写一次重规划。

### 为什么放弃了 `IsPathValid` 触发式方案

`IsPathValid` 方案本身更灵敏（被堵时立刻重规划，不用等卡死），但和「不清全局图」的需求叠加后暴露一个缺陷链：

> 恢复动作清空全局图 → 图上没有障碍 → `IsPathValid` 必然返回有效 → 主分支不重规划 → 机器人沿原路径走回被堵处 → 全局图按 0.5 Hz 花数秒重新填回障碍 → 再次判出堵塞 → 才重规划

来回浪费数秒。既然用户明确要求不清全局图，触发式的灵敏度优势也就没了必要，严格版更简单可控。

### 遗留风险（按严重程度）

**1. 全局图鬼影会永久累积——最大的风险。**

`config/go2_nav2_stvl.yaml` 第 222-229 行的注释已经论证过：`VoxelLayer` 的清除依赖 3D 射线，D435i 71° 水平视锥给不了 6×6 m 局部图侧后方任何清除射线。**局部层因此换成了 STVL 靠 `voxel_decay` 自然过期，但全局层（第 325 行）仍是 `VoxelLayer`**，它此前唯一的兜底就是恢复行为那次清图，现在这个兜底被移除了。

后果：长时间运行后全局图上会攒下清不掉的 254 格，叠加 `allow_unknown: false`，最终让 `ComputePathToPose` 直接规划失败。

缓解方向（未实施）：全局层也换成 STVL（`voxel_decay` 设 30~60 s），或去掉全局 `voxel_layer` 只留 `static_layer`，让 RTAB-Map 的 `/map` 自己管障碍。

**2. `/goal_update` 话题的动态目标更新失效。**
`GoalUpdater` 只写 `{updated_goal}`，不改黑板 `{goal}`，而触发条件读的是 `{goal}`。以前靠每 2 秒规划一次顺带生效，现在不会了。走 action 下发目标（RViz、`waypoint_follower`）不受影响。

**3. through_poses 树有一个无法回避的例外：每经过一个航点会重规划一次。**
`RemovePassedGoals` 必须每 tick 执行——它只连续移除距机器人 `transform_tolerance + radius` 以内的队首航点，`while` 循环遇到超距即 `break`，一旦驶离该航点就再也移不掉。若只在恢复时才 tick 它，已走过的航点仍留在 `{goals}` 里，恢复后的重规划会规划出一条先回头去旧航点的路径。而它改写 `{goals}` 就会被 `GlobalUpdatedGoal` 判为目标变更。这属于目标集合真的变了，不是周期规划。

**4. 遇到堵塞固定浪费约 5 秒。**
没有任何东西检测路径失效，MPPI 会顶着膨胀带磨到 `movement_time_allowance: 5.0` 进度超时，才进恢复、才重规划。这是严格版的既定代价。

### 配套建议（未实施）

`config/go2_nav2_stvl.yaml:392` 的 `cache_obstacle_heuristic: true` 原本是为了压制「地图微变→启发式变→展开顺序变→路径跳变」。周期规划取消后这个动机消失，而它的代价（启发式基于旧代价地图）仍在。建议改回 `false`，让恢复时那次重规划用最新地图的启发式。

`expected_planner_frequency` 不用动（见上文，它只控制 WARN）。

### 部署与验证

**[已验证]** `install` 是符号链接链条 `install → build → src`：

```
install/.../config/navigate_to_pose_no_backup.xml
  -> build/robot_slam_bringup/config/navigate_to_pose_no_backup.xml
  -> src/robot_slam_bringup/config/navigate_to_pose_no_backup.xml
```

所以改 XML **不需要 `colcon build`**，直接重启 nav2 即生效。

```bash
# XML 语法自检（两个文件均已通过）
python3 -c "import xml.etree.ElementTree as E; E.parse('navigate_to_pose_no_backup.xml')"

# 改前稳定 0.5 Hz；改后应只在发目标 / 触发恢复时冒出单条消息
ros2 topic hz /plan

# 重点观察：恢复行为是否会轮到 BackUp（验证上文的 BT.CPP 假设）
```

---

## 第二部分：OpenVINS 里程计漂移（排查中，未实施改动）

### 现象

`config/go2_d435i_openvins_leg_mapping_optimized.yaml` 配置下里程计容易漂移。

### 前提澄清：IMU 到底是哪一颗

这是整个排查的分水叉。用户确认**使用 D435i 内置 IMU**（BMI055），而**当前 launch 与 yaml 全部是为外置 WIT IMU 写的**。

`launch/go2_d435i_openvins_leg_mapping.launch.py:244-245` 的注释原文：

> 只启用红外双目。使用外置 WIT 后关闭 D435i 内置运动模块，避免之前日志中的 Motion Module hardware failure 及额外 USB/CPU 开销。

由此产生三处配置错位。

### 错位一：D435i 的 IMU 在 launch 里是全关的

`launch/go2_d435i_openvins_leg_mapping.launch.py:267-270`：

```python
"enable_gyro": False,
"enable_accel": False,
"enable_motion": False,
"unite_imu_method": 0,
```

**[已验证]** `unite_imu_method` 的取值语义，来自本机 `/opt/ros/humble/share/realsense2_camera/launch/rs_launch.py:69`：

```python
{'name': 'unite_imu_method', 'default': "0", 'description': '[0-None, 1-copy, 2-linear_interpolation]'}
```

**`0` = None = 不发布合成的 `/camera/camera/imu` 话题**，只会有 `accel/sample` 和 `gyro/sample` 两路裸流。而 OpenVINS 订阅的正是 `/camera/camera/imu`，且 `wait_imu_to_init: true`。

要用 D435i IMU 必须改为：

```python
"enable_gyro": True,
"enable_accel": True,
"enable_motion": True,
"unite_imu_method": 2,      # linear_interpolation；1(copy) 会产生阶梯状 accel
"gyro_fps": 200,
"accel_fps": 250,
```

**[已验证]** 本机 `librealsense2_camera.so` 中存在提示串：`For the 'unite_imu_method' param update to take effect, re-enable either gyro or accel stream.` —— 该参数不能单独热改，必须重新使能数据流。

重新开启后若复现历史上的 `Motion Module hardware failure`，先试 `initial_reset: True`，再查 USB 供电与固件版本。

### 错位二：静态 TF 外参是 WIT 的，套到 D435i 上会灾难性漂移

`launch/go2_d435i_openvins_leg_mapping.launch.py:307-324` 的 `camera_to_wit_imu_tf`（2026-08-03 Kalibr 标定，`camera_link → imu_link`）：

```
--x -0.03453964436591465  --y -0.020484129171029215  --z 0.00486747161468371
--qx 0.7052099474822251   --qy -0.011074111237417432
--qz -0.7087317863872082  --qw 0.015985899937620437
```

**[已验证]** 数值换算：总平移模长 **4.0 cm**；`qw = 0.01599` → 旋转角 `2·acos(qw)` = **176.2°**，接近整个坐标系翻转。

这是外置 WIT IMU 的安装位置。D435i 内置 IMU 的 frame 是 `camera_imu_optical_frame`，由 realsense 自己按出厂外参发布（`publish_tf: True`），两者完全不是一个东西。

**[待确认]** 判据是 IMU 消息的 `header.frame_id`：

| `frame_id` | 结论 |
|---|---|
| `camera_imu_optical_frame` | 用的是出厂外参，正确。建议 `publish_camera_imu_tf:=false` 关掉 WIT 那条静态 TF，免得 TF 树里留一个误导性的 `imu_link` |
| `imu_link` | **正在把 176° 翻转 + 4 cm 偏移的错误外参套到 D435i IMU 上**。这一条足以单独造成剧烈漂移，其他参数都不必调 |

### 错位三：IMU 噪声参数量级不对（`optimized.yaml:113-116`）

当前值（注释标明是「WIT IMU 当前标定噪声」）与 D435i 基准的对照。

**[已验证]** 基准取自本机 OpenVINS 源码 `/root/robot_ws/openvins_ws/src/open_vins/config/rs_d455/kalibr_imu_chain.yaml` —— D455 与 D435i 使用同一颗 BMI055 模块系列：

| 参数 | 当前值 | `rs_d455` 基准 | 倍数 |
|---|---|---|---|
| `AccelerometerNoiseDensity` | 0.08 | 0.00207649074 | **38×** |
| `AccelerometerRandomWalk` | 0.004 | 0.00041327852 | **9.7×** |
| `GyroscopeNoiseDensity` | 0.001 | 0.00020544166 | **4.9×** |
| `GyroscopeRandomWalk` | 0.0001 | 0.00001110622 | **9×** |

两个后果：

1. **四项整体偏大** → EKF 整体不信任 IMU。视觉好时看不出来，但四足运动模糊、低纹理导致视觉退化时，IMU 也不被信任，状态协方差直接膨胀 → 漂移。
2. **相对失衡**：accel noise density 相对 gyro 被额外放大约 8 倍（38÷4.9）。加速度计对重力方向的约束被削弱 → roll/pitch 估计变差 → 重力投影错误 → 水平方向出现虚假加速度 → 位置漂移。`random walk` 偏大 9~10 倍还会让零偏估计跟着噪声游走、不收敛，这正是「容易飘」的典型症状。

**一个有用的旁证**：`rs_d455` 文件里被注释掉的那组是 Allan 方差原始值（accel `0.0010382453726199955`、gyro `0.00010272083263292572`），启用的那组正好是它的 **2 倍**。官方做法是标定值放大 2 倍再用，不是放大 40 倍。

建议起点（按 D455 基准等比放大 2 倍，**保持 accel/gyro 相对平衡比绝对值更重要**）：

```yaml
    "OdomOpenVINS/AccelerometerNoiseDensity": "0.004"
    "OdomOpenVINS/AccelerometerRandomWalk": "0.0008"
    "OdomOpenVINS/GyroscopeNoiseDensity": "0.0004"
    "OdomOpenVINS/GyroscopeRandomWalk": "0.00002"
```

### 本机可用的 IMU 噪声基准库

**[已验证]** `/root/robot_ws/openvins_ws/src/open_vins/config/*/kalibr_imu_chain.yaml` 是一份现成的量级参照表，调参时值得先查它再动手：

| 配置 | accel noise | accel RW | gyro noise | gyro RW | rate |
|---|---|---|---|---|---|
| `rs_d455` | 2.076e-3 | 4.133e-4 | 2.054e-4 | 1.111e-5 | 400 |
| `rpng_plane` | 2.076e-3 | 4.133e-4 | 2.054e-4 | 1.111e-5 | 400 |
| `euroc_mav` | 2.000e-3 | 3.000e-3 | 1.697e-4 | 1.939e-5 | 200 |
| `rpng_ironsides` | 2.705e-3 | 1.305e-4 | 1.119e-4 | 9.00e-7 | 200 |
| `kaist` | 5.886e-3 | 1.000e-4 | 1.745e-4 | 1.000e-5 | 500 |
| `kaist_vio` | 0.07 | 0.009 | 0.001 | 0.0003 | 100 |

注意 `kaist_vio` 那一行：`accel 0.07 / gyro 0.001` 与本项目当前值几乎一致，而它注释掉的原始标定值是 `accel 0.0033 / gyro 0.0000577` —— 即放大了 21 倍和 17 倍。**所以当前配置不是荒谬的（有先例），只是对 D435i 过于保守**，而且它对应的是 100 Hz 低速 IMU。

### 一条需要撤回的先前判断

排查早期曾把 `wit_imu` 驱动「用 `expected_rate_hz` 递推时间戳、每 20 ms 硬跳」列为最可能的根因。

**在使用 D435i 内置 IMU 的前提下这条完全不适用** —— D435i 的 IMU 与图像共用相机时钟，时间同步天然优于外置 IMU，那套递推逻辑根本不经手。这反而是内置 IMU 相对 WIT 的一项固有优势。

### 当前优先级排序

1. **外参 `frame_id` 错位**（若命中，单独就能解释全部漂移）
2. **IMU 根本没被开启**（`enable_*: False` + `unite_imu_method: 0`）
3. **噪声参数量级**（`optimized.yaml:113-116`）
4. 其后才轮到 `ZUPTOnlyAtBeginning: true`（第 110 行）、`UpMSCKFChi2Multiplier: 1.5`（第 118 行）等策略性参数

### 下一步实测清单

```bash
ros2 topic echo /camera/camera/imu --once     # 看 header.frame_id —— 决定第 1 项是否命中
ros2 topic hz  /camera/camera/imu             # 确认合成频率是否接近 gyro_fps
ros2 node list | grep wit                     # WIT 节点是否仍在跑（判断 start_wit_imu 实际取值）
ros2 run tf2_ros tf2_echo camera_link imu_link   # 确认这条 TF 是否真的被消费
```

### 排查过程中的一个教训

本次尝试用 `ros2 param get /camera/camera <param>` 读取相机节点的实际 IMU 参数，六次调用全部 `Terminated`（超时），`ros2 topic list | grep -i camera` 也返回空 —— 节点在列表里但没有真正发布任何话题。**「节点存在」不等于「节点就绪」**，运行时真值取不到时应当明确说明拿不到，而不是退回配置文件推理。

---

## 通用方法论小结

1. **先确认参数到底控制什么，再动手。** `expected_planner_frequency` 看名字像是重规划频率，实际只控制一行 WARN；重规划频率在 BT XML 的 `RateController` 里。名字像的参数往往不是。
2. **量级基准优先从本机已有源码取，不靠记忆。** `open_vins/config/*/kalibr_imu_chain.yaml` 和 `realsense2_camera/launch/rs_launch.py` 都在本机，比任何回忆都可靠。
3. **换硬件时，配套的三样东西都要跟着换**：数据源开关、外参 TF、噪声模型。本次 D435i / WIT 的错位正是只换了想法没换配置。
4. **相对平衡比绝对值重要。** IMU 噪声参数四项等比缩放的影响，远小于 accel 与 gyro 之间失衡 8 倍的影响。
5. **删掉兜底机制前，先确认它在兜什么。** 移除「恢复时清全局图」看起来只是少做一件事，实际拆掉了 `VoxelLayer` 射线清不干净的唯一补救措施。
6. **silent failure 要写进注释。** BT.CPP 的 `haltChild` 假设失效时不报错，只是恢复行为悄悄不轮换，所以判据和替代方案已直接写在 XML 注释里。
