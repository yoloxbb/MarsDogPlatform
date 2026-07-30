# stereo_slam_legacy_bringup

本包集中保存原先混在 `stereo_camera_pkg` 和 `stereo_camera_pkg_py` 中的历史
RTAB-Map、OpenVINS、EKF 和 Nav2 入口，用于兼容已有实验命令。

新项目应优先使用 `robot_slam_bringup`。兼容入口完成实机回归并确认不再使用后，
可以按功能逐步合并或删除；不要把这些文件移回传感器包。
