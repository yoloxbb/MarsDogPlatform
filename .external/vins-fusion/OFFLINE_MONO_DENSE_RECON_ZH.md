# 单目 + IMU 离线半稠密重建流程

本文档记录当前工作区已经跑通的离线单目半稠密重建流程。目标是用 VINS-Fusion 的单目 IMU 位姿提供真实尺度，再用 `/cam0/image_raw` 多帧图像做 plane-sweep 光度匹配，输出 PLY 点云。

当前实现不依赖 COLMAP、Open3D 或 SciPy，只使用 Python、OpenCV、NumPy 和 rosbags。

执行本文命令前先运行 `source ~/robot_ws/scripts/setup_robot_env.sh`，统一设置仓库和输出目录。

## 1. 当前产物

工具脚本：

```text
tools/dense_recon/export_mono_images.py
tools/dense_recon/prepare_vins_poses.py
tools/dense_recon/monocular_planesweep.py
tools/dense_recon/README.md
```

已验证输出：

```text
${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt
${ROBOT_OUTPUT_DIR}/dense_recon/cam_poses_tum.txt
${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv
${ROBOT_OUTPUT_DIR}/dense_recon/planesweep_keyframes.csv
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_raw.ply
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply
```

本次测试结果：

| 项目 | 结果 |
|------|------|
| 导出图像 | 2912 张 |
| 匹配相机位姿 | 1401 帧 |
| 最大图像-位姿时间差 | 0.000000 s |
| raw 点云 | 243113 点 |
| voxel 3cm 点云 | 164318 点 |
| raw 点云坐标范围 | x: -10.995876 到 10.484457, y: -12.682101 到 8.129276, z: -6.663147 到 2.112328 |

## 2. 重新运行 VINS 生成轨迹

先确认已经编译最新 `vins` 包，并且 `vio.csv` 第一列会输出小数秒时间戳。

终端 1：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run vins vins_node config/euroc/euroc_mono_imu_config.yaml
```

终端 2：

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 bag play datasets/euroc/V1_01_easy_mono_imu_ros2 --rate 1.0
```

输出轨迹：

```text
${ROBOT_OUTPUT_DIR}/vio.csv
```

检查时间戳，第一列应类似：

```text
1403715278.812143087
```

如果第一列只有整数秒，例如 `1403715279`，需要重新编译并重跑 VINS，否则图像和位姿同步会很差。

## 3. 导出单目图像

```bash
cd ${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm

python3 tools/dense_recon/export_mono_images.py \
  --bag datasets/euroc/V1_01_easy_mono_imu_ros2 \
  --topic /cam0/image_raw \
  --output ${ROBOT_OUTPUT_DIR}/dense_recon/images \
  --times ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt \
  --overwrite
```

验证：

```bash
wc -l ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt
du -sh ${ROBOT_OUTPUT_DIR}/dense_recon/images
```

当前验证结果：

```text
2913 ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt
543M  ${ROBOT_OUTPUT_DIR}/dense_recon/images
```

`image_times.txt` 第一行是表头，所以实际图像数量是 2912 张。

## 4. 准备相机位姿

该步骤读取：

```text
${ROBOT_OUTPUT_DIR}/vio.csv
${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt
config/euroc/euroc_mono_imu_config.yaml
```

并使用配置里的 `body_T_cam0` 将 VINS 的 body 位姿转换为相机位姿：

```text
T_w_c = T_w_b * T_b_c
```

运行：

```bash
python3 tools/dense_recon/prepare_vins_poses.py \
  --vio ${ROBOT_OUTPUT_DIR}/vio.csv \
  --image-times ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt \
  --config config/euroc/euroc_mono_imu_config.yaml \
  --output-tum ${ROBOT_OUTPUT_DIR}/dense_recon/cam_poses_tum.txt \
  --output-frames ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv
```

验证：

```bash
wc -l ${ROBOT_OUTPUT_DIR}/dense_recon/cam_poses_tum.txt
wc -l ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv
head -n 3 ${ROBOT_OUTPUT_DIR}/dense_recon/cam_poses_tum.txt
```

当前验证结果：

```text
Matched 1401 / 2912 images
Max accepted time delta: 0.000000s
```

## 5. 运行 plane-sweep 半稠密重建

先用小参数做 smoke test：

```bash
python3 tools/dense_recon/monocular_planesweep.py \
  --frames ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv \
  --camera config/euroc/cam0_pinhole.yaml \
  --output-dir ${ROBOT_OUTPUT_DIR}/dense_recon_smoke \
  --max-ref-frames 2 \
  --depth-samples 8 \
  --stride 12 \
  --source-search-window 40 \
  --max-sources 3
```

确认能生成 PLY 后，运行较完整参数：

```bash
python3 tools/dense_recon/monocular_planesweep.py \
  --frames ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv \
  --camera config/euroc/cam0_pinhole.yaml \
  --output-dir ${ROBOT_OUTPUT_DIR}/dense_recon \
  --max-ref-frames 80 \
  --depth-samples 64 \
  --stride 4 \
  --source-search-window 80 \
  --max-sources 4 \
  --gradient-threshold 14 \
  --max-photo-cost 26 \
  --uniqueness-margin 1.5
```

输出：

```text
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_raw.ply
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply
${ROBOT_OUTPUT_DIR}/dense_recon/planesweep_keyframes.csv
```

## 6. 验证点云

检查文件大小：

```bash
ls -lh ${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_raw.ply
ls -lh ${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply
```

检查 PLY 点数和坐标范围：

```bash
python3 - <<'PY'
from pathlib import Path
import numpy as np
import struct

for path in [
    Path('${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_raw.ply'),
    Path('${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply'),
]:
    with path.open('rb') as f:
        while True:
            line = f.readline().decode('ascii').strip()
            if line.startswith('element vertex'):
                count = int(line.split()[-1])
            if line == 'end_header':
                break
        data = f.read()

    points = np.empty((count, 3), dtype=np.float32)
    for i in range(count):
        points[i] = struct.unpack_from('<fff', data, i * 15)

    print(path.name)
    print('points:', count)
    print('finite:', bool(np.isfinite(points).all()))
    print('min:', points.min(axis=0))
    print('max:', points.max(axis=0))
PY
```

当前验证结果：

```text
pointcloud_raw.ply
points: 243113
finite: True
min: [-10.995876 -12.682101  -6.663147]
max: [10.484457   8.129276   2.1123276]

pointcloud_voxel_3cm.ply
points: 164318
finite: True
min: [-10.995876 -12.682101  -6.663147]
max: [10.484457   8.129276   2.1123276]
```

## 7. 查看点云

可以把 PLY 拷到宿主机或安装点云查看器打开：

```bash
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply
```

推荐先看 voxel 版本，因为点数更少，打开更快。

## 8. 注意事项

- 这是单目 + IMU 离线半稠密重建，不是实时稠密 SLAM。
- IMU/VINS 提供尺度和相机位姿，像素深度仍来自多帧图像光度匹配。
- 纯旋转、弱纹理、动态物体、曝光变化都会降低点云质量。
- 如果点云拉伸严重，优先检查 `vio.csv` 时间戳是否为小数秒，以及 `matched_frames.csv` 的 `time_delta` 是否接近 0。
- 如果点云点数太少，可降低 `--gradient-threshold`、降低 `--stride` 或增加 `--max-ref-frames`。
- 如果点云噪声太多，可降低 `--max-photo-cost`、提高 `--uniqueness-margin` 或增大 `--min-baseline`。
- 当前导出的图像约占 543M，磁盘紧张时可以删除 smoke/test 输出目录：

```bash
rm -rf ${ROBOT_OUTPUT_DIR}/dense_recon_smoke
rm -rf ${ROBOT_OUTPUT_DIR}/dense_recon_test
```
