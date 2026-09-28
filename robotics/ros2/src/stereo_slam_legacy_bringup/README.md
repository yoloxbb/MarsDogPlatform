# stereo_slam_legacy_bringup

本包只保留仍有用途的兼容入口。新项目应优先使用
`robot_slam_bringup/launch/nav.launch.py`。

## 保留文件

- `ekf_rtabmap.launch.py`：唯一的双目视觉里程计 + 轮式/足式里程计 EKF 融合入口，
  RTAB-Map 明确订阅 `/odometry/filtered`。
- `d435i_openvins_rtabmap.launch.py`：D435i OpenVINS 兼容入口；当前存在本地未提交
  修改，因此保留。
- `rtabmap_openvins_stereo_mapping.launch.py`：上述兼容入口依赖的公共管线。

EKF 融合入口：

```bash
ros2 launch stereo_slam_legacy_bringup ekf_rtabmap.launch.py
```
