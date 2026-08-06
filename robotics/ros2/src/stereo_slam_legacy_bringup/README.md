# stereo_slam_legacy_bringup

本包集中保存原先混在 `stereo_camera_pkg` 和 `stereo_camera_pkg_py` 中的历史
RTAB-Map、OpenVINS、EKF 和 Nav2 入口，用于兼容已有实验命令。

新项目应优先使用 `robot_slam_bringup`。兼容入口完成实机回归并确认不再使用后，
可以按功能逐步合并或删除；不要把这些文件移回传感器包。

## OpenVINS 足式速度辅助

原入口 `d435i_openvins_rtabmap.launch.py` 默认关闭足式辅助，行为与原版本一致。
需要在视觉退化时启用四维足式速度约束时使用：

```bash
ros2 launch stereo_slam_legacy_bringup \
  d435i_openvins_leg_velocity_rtabmap.launch.py
```

输入话题默认为 `/odom_leg`，消息必须满足：

- `header.stamp` 使用发布端当前 `now()`，不要固定增加 30 ms；如存在实测时偏，使用
  `OdomOpenVINS/LegVelocityTimeOffset` 配置。
- `child_frame_id=base_link`，并与 OpenVINS 节点的 `frame_id` 一致。
- `twist.twist.linear.{x,y,z}` 是 `base_link` 原点的真实三维速度，且表达在
  `base_link` 下；`linear.z` 必须来自可靠足式运动学，无法保证时应设置
  `OdomOpenVINS/LegVelocityUseVertical=false`。
- `twist.twist.angular.z` 是独立足式运动学的偏航角速度。roll/pitch 角速度不作为
  观测输入，但头部 IMU 的完整角速度会用于杆臂补偿。
- `twist.covariance` 的行列索引 `{0,1,2,5}` 必须给出动态、有限的完整 `4×4`
  协方差子矩阵，包含已知的交叉协方差。

该入口不启动 `robot_localization`，也不会因视觉丢失重置 OpenVINS。模式、视觉
统计、消息年龄、四维创新、卡方门控结果和实际 IMU 杆臂可在 `/diagnostics` 及
`[OV-LEG]` 日志中查看。
