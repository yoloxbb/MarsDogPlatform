# Offline monocular dense reconstruction

This folder contains a lightweight offline pipeline for monocular + IMU
semi-dense reconstruction from VINS-Fusion output.

It uses only `cv2`, `numpy`, and `rosbags`; it does not require COLMAP,
Open3D, or SciPy.

Source `~/robot_ws/scripts/setup_robot_env.sh` before running the commands so
`ROBOT_OUTPUT_DIR` follows the current clone location.

## 1. Export images

```bash
python3 tools/dense_recon/export_mono_images.py \
  --bag datasets/euroc/V1_01_easy_mono_imu_ros2 \
  --topic /cam0/image_raw \
  --output ${ROBOT_OUTPUT_DIR}/dense_recon/images \
  --times ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt \
  --overwrite
```

## 2. Prepare camera poses

Run VINS first so `${ROBOT_OUTPUT_DIR}/vio.csv` is fresh and has fractional
timestamps. Then convert the body trajectory into camera poses:

```bash
python3 tools/dense_recon/prepare_vins_poses.py \
  --vio ${ROBOT_OUTPUT_DIR}/vio.csv \
  --image-times ${ROBOT_OUTPUT_DIR}/dense_recon/image_times.txt \
  --config config/euroc/euroc_mono_imu_config.yaml \
  --output-tum ${ROBOT_OUTPUT_DIR}/dense_recon/cam_poses_tum.txt \
  --output-frames ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv
```

## 3. Run plane sweep

Start with a small run:

```bash
python3 tools/dense_recon/monocular_planesweep.py \
  --frames ${ROBOT_OUTPUT_DIR}/dense_recon/matched_frames.csv \
  --camera config/euroc/cam0_pinhole.yaml \
  --output-dir ${ROBOT_OUTPUT_DIR}/dense_recon \
  --max-ref-frames 8 \
  --depth-samples 32 \
  --stride 5
```

Then increase `--max-ref-frames`, `--depth-samples`, and lower `--stride` if
the result is reasonable.

Main outputs:

```text
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_raw.ply
${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply
```

The result is semi-dense and depends heavily on parallax, texture, and VINS
pose quality.

## 4. Visualize in RViz

```bash
source /opt/ros/humble/setup.bash
python3 tools/dense_recon/publish_ply_to_rviz.py \
  --ply ${ROBOT_OUTPUT_DIR}/dense_recon/pointcloud_voxel_3cm.ply \
  --topic /dense_recon/cloud \
  --frame-id world
```

In another terminal:

```bash
source /opt/ros/humble/setup.bash
rviz2
```

Set `Fixed Frame` to `world`, add a `PointCloud2` display, and select
`/dense_recon/cloud`.
