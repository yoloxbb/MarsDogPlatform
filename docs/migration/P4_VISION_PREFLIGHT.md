# P4b — Vision 环境与打包预检（2026-09-29）

状态：尚未导入 Vision。独立 ROS 构建与 wheel 文件清单检查完成；原锁 Python
环境尚未完整恢复，不能宣称单元测试、安装运行或模型验收通过。

## 已核对的代码事实

- 源快照：/home/elephant/MarsDog/migration/work/p1-20260928/sources/vision。
- Python >=3.10,<3.11，ROS 2 Humble，package marsdog_vision_interaction，
  原 VisionTask.srv 保持不变。
- 原 README 要求 uv sync --extra models --extra dev；本次按该完整组合恢复，
  不降级、不删除 Ultralytics/Torch、不改为 CPU 特供版本。
- 锁文件同时含 opencv-python 和 opencv-contrib-python 4.11.0.86；需在实际
  安装后检查 cv2 文件覆盖及功能可用性，不直接合并/删掉依赖。
- NumPy 1.26.4、Torch 2.13.0、torchvision 0.28.0、MediaPipe 0.10.18、
  protobuf 4.25.9、pydantic 2.13.5。Voice 的 pydantic 是 2.13.4，Action 的
  NumPy 是 2.2.6；模块继续隔离，不强制统一版本。
- rknn-toolkit-lite2 2.3.2 仅在 Linux AArch64 安装，x86 测试不能代替 RK3588。
- CMake 的 hand RGA bridge 是可选；本机没有 librga headers/library，所以本次
  build 没有编译该 bridge。DMA-BUF/RGA/RKNN probe 默认 OFF，未开启。

依据：原 pyproject.toml、uv.lock、README.md、CMakeLists.txt。锁定依赖的直接
依赖关系保存在 validation/p4-vision/locked-runtime-inventory.json。
这个 JSON 是锁文件清单，不是已经安装的环境清单。

## ROS 与 wheel 预检

原包独立 colcon 构建通过，未执行节点、相机、模型或板端 probe。
原 wheel 可以构建，并包含 YAML、launch 和 web/dashboard.html。

确认的原打包差异：
- setup.py 的 data_files 仅收集 config/*.yaml；
- 原 wheel 无 config/fastdds.xml，也没有 scripts/fastdds_env.sh；
- launch/vision.launch.py:28 与 launch/vision_debug.launch.py:45 默认解析
  share/marsdog_vision_interaction/config/fastdds.xml；
- ROS CMake 安装 config 目录及 fastdds_env.sh，具有这些资源。

因此只安装 Python wheel 后不能假定这些 launch 资源齐全。后续要在 clean
install 中明确 wheel 与 ROS 安装的使用边界，再决定是否做小范围打包修复。
此轮未修改 setup.py 或任何 Vision 源码，也未用 wheel 构建成功替代运行测试。
证据：validation/p4-vision/original-wheel-inventory.json 和 original-ros-build.json。

## 环境恢复与后续执行

在线恢复使用独立快照、原 lock 和 retained uv cache；日志在
/home/elephant/MarsDog/migration/reports/p1-20260928/p4-vision-sync-full.log。
准确执行结果见 validation/p4-vision/environment-attempt.json。

后续先完成锁环境，再运行原测试。节点相关测试需要 Humble；先检查测试对
设备/模型的使用，保留 RGA parity smoke 的显式 skip 原因。不要伪造模型或把
系统 cv2/另一模块环境当作完整原 lock 验证。再做 clean install、mock transport、
资源与模式比较、bundle 和 Git 历史导入。未通过 gate 前不创建 modules/vision。

默认数据/模型根目录由 utils/config_loader.py 解析，支持
MARSDOG_VISION_PROJECT_DIR/MODEL_DIR/DATA_DIR。部署路径必须明确配置，不能复制
人脸数据或以目录搬迁隐式改变注册表位置。任何真实设备/模型验收继续独立记录。
