# VINS-Fusion (ROS2 Humble) 构建与运行记录

本文档记录在本机（Ubuntu 22.04 + ROS2 Humble）上构建并运行本项目的完整步骤、遇到的问题及解决方案。

执行本文命令前先运行 `source ~/robot_ws/scripts/setup_robot_env.sh`；仓库不在默认位置时，直接 source 实际克隆目录中的同名脚本。

- 项目路径：`${ROBOT_WS_ROOT}/VINS-Fusion-ROS2-humble-arm`
- 该目录本身即 colcon 工作空间，直接在此目录执行 `colcon build`
- 包含 4 个包：`camera_models`、`global_fusion`、`loop_fusion`、`vins`

---

## 1. 环境与依赖现状

构建前检查结果：

| 依赖 | 状态 | 说明 |
|------|------|------|
| ROS2 Humble | ✅ 已装 | `/opt/ros/humble` |
| OpenCV | ✅ 4.5.4（系统 apt 版） | 未使用 `/usr/local` 源码版，避免与 cv_bridge 冲突 |
| Eigen | ✅ 3.4.0 | 已装 |
| cv_bridge / image_transport | ✅ apt 已装 | 基于系统 OpenCV 4.5.4 |
| Ceres Solver | ❌ 缺失 | 需安装（下文） |
| GPU_MODE | 已关闭 | `vins/src/featureTracker/feature_tracker.h:14` 该宏被注释，走 CPU 路径，无需 CUDA |

**决策**：不执行仓库自带的 `install_external_deps.sh`。
原因：该脚本会从源码编译 OpenCV 4.8.0 到 `/usr/local`，一方面 ARM/本机源码编译极慢，另一方面会与已有的 apt 版 cv_bridge（链接系统 OpenCV 4.5.4）产生版本冲突。
最终方案：**仅用 apt 安装 Ceres，其余全部使用系统库**。

---

## 2. 安装 Ceres（含依赖冲突处理）

### 2.1 libunwind 冲突

直接 `apt install libceres-dev` 失败，报 `libgoogle-glog-dev` 依赖 `libunwind-dev` 无法安装。
根因：系统装的是 LLVM 版 `libunwind-14-dev`，而 glog 需要标准 `libunwind-dev`（1.3.2）。

解决（会移除 `libc++-14-dev`、`libc++-dev`、`libunwind-14-dev`，对本项目无影响）：

```bash
sudo apt-get install -y libunwind-dev
```

### 2.2 安装 Ceres

```bash
sudo apt-get install -y libceres-dev
```

安装版本为 **Ceres 2.0.0**（apt 候选版）。注意：仓库脚本原意为 2.1.0，版本差异导致下面第 3 节的代码兼容性问题。

---

## 3. 代码修改：Ceres 2.0 兼容性

### 问题
`vins` 编译报错：

```
vins/src/estimator/estimator.cpp:1171:60: error: ‘CUDA’ is not a member of ‘ceres’
```

`ceres::CUDA`（`dense_linear_algebra_library_type`）是 **Ceres 2.1.0** 才引入的枚举，2.0.0 没有。
该行只在 `USE_GPU_CERES` 为真时使用，而 EuRoC 配置中 `use_gpu_ceres: 0`，运行时根本不会走到；但编译期仍需该符号存在。

### 修改
文件：`vins/src/estimator/estimator.cpp`（约 1169 行），用 Ceres 版本宏做条件编译保护，2.1+ 才启用 CUDA，否则退回 CPU 的 `DENSE_SCHUR`：

```cpp
#if (CERES_VERSION_MAJOR > 2) || (CERES_VERSION_MAJOR == 2 && CERES_VERSION_MINOR >= 1)
    if (USE_GPU_CERES)
        // std::cout << "1" << endl;
        options.dense_linear_algebra_library_type = ceres::CUDA;
    else
        // std::cout << "2" << endl;
        options.linear_solver_type = ceres::DENSE_SCHUR;
#else
    // Ceres < 2.1 has no CUDA dense linear algebra backend; fall back to CPU.
    options.linear_solver_type = ceres::DENSE_SCHUR;
#endif
```

> `CERES_VERSION_MAJOR/MINOR` 宏由 `<ceres/ceres.h>` 引入的 `ceres/version.h` 提供，无需额外 include。

---

## 4. 构建

在项目根目录依次构建（`camera_models` 是其他包的依赖，先构建）：

```bash
cd ~/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash

# 1) 先构建依赖包 camera_models
colcon build --symlink-install --packages-select camera_models
source install/setup.bash

# 2) 再构建其余包
colcon build --symlink-install --packages-select vins loop_fusion global_fusion
```

或一次性全部构建：

```bash
cd ~/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

**结果**：4 个包全部构建成功（仅有无害编译警告）。

- `camera_models` ≈ 2min32s
- `global_fusion` ≈ 1min56s
- `vins` ≈ 1min52s
- `loop_fusion` 秒级完成

---

## 5. 示例数据（EuRoC V1_02_medium）

### 5.1 下载

仓库脚本 `get_example_data.sh` 下载的是 **ROS1 格式** 的 `V1_02_medium.bag`：

```bash
./get_example_data.sh
# 实际地址：
# http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/vicon_room1/V1_02_medium/V1_02_medium.bag
```

> ⚠️ **待解决问题**：当前网络下该下载**未成功**。
> - HTTP 版返回 `502 Bad Gateway`（经本机代理 `127.0.0.1:7897`）。
> - HTTPS 版可建立连接（`200 Connection established`），但完整下载尚未验证通过。
> - 首次用 `wget -q` 下载得到 **0 字节** 空文件（`-q` 静默吞掉了错误）。
>
> 后续可尝试：改用 HTTPS 地址下载、更换镜像源，或使用已有的其他 EuRoC ROS2 bag。

### 5.2 转换为 ROS2 格式

`ros2 bag play` 无法直接播放 ROS1 bag，需用 `rosbags-convert`（本机已装于 `~/.local/bin/rosbags-convert`）转换：

```bash
rosbags-convert V1_02_medium.bag --dst V1_02_medium   # 生成 ROS2 bag 目录
```

如未安装：`pip install rosbags`

---

## 6. 运行

数据中的话题（见 `config/euroc/euroc_stereo_imu_config.yaml`）：

- IMU：`/imu0`
- 左目：`/cam0/image_raw`
- 右目：`/cam1/image_raw`

开多个终端，每个终端先 source：

```bash
cd ~/VINS-Fusion-ROS2-humble-arm
source /opt/ros/humble/setup.bash
source install/setup.bash
```

**终端 1 —— 启动 RViz（可视化，可选）**

```bash
ros2 launch vins vins_rviz.launch.xml
```

**终端 2 —— 启动 VINS 节点（双目 + IMU 配置）**

```bash
ros2 run vins vins_node config/euroc/euroc_stereo_imu_config.yaml
```

其他传感器组合可换配置文件：
- 单目 + IMU：`config/euroc/euroc_mono_imu_config.yaml`
- 纯双目：`config/euroc/euroc_stereo_config.yaml`

**终端 3 —— （可选）回环检测**

```bash
ros2 run loop_fusion loop_fusion_node config/euroc/euroc_stereo_imu_config.yaml
```

**终端 4 —— 播放数据**

```bash
ros2 bag play V1_02_medium   # 转换后的 ROS2 bag 目录
```

RViz 中：绿色轨迹为 VIO 里程计，红色轨迹为经回环闭合后的里程计。

---

## 7. 当前进度小结

- [x] 依赖检查（OpenCV/Eigen/cv_bridge 均就绪）
- [x] 解决 libunwind 冲突并安装 Ceres 2.0.0
- [x] 修复 `ceres::CUDA` 版本兼容问题（条件编译）
- [x] 4 个包全部构建成功
- [ ] 示例 bag 下载（网络/代理导致失败，待重试）
- [ ] 数据转换为 ROS2 格式
- [ ] 端到端运行验证
