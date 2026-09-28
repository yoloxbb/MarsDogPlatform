# P4b — Vision 软件迁移完成（2026-09-29）

Vision 已进入 modules/vision，原 Python namespace、ROS 包、VisionTask 和默认配置保留。
32 个可达提交已归档并验证 bundle 恢复/refs/fsck；125 个原文件按前缀原样导入。
证据：history/vision-import.json、vision-commit-map.txt。

原仓和迁移后完整 Humble 单元测试均为 **280 passed / 3 skipped**。
三个 skip 只属于显式要求 RGA helper 的图像对照测试，不能视为板端通过。
原始锁定 dev+models 环境已恢复；早先 environment-attempt.json 的超时是历史记录，
已由本次测试和 validation/p4-vision/equivalence.json 的安装观察补充。

独立 wheel 安装使用原锁、CPU Torch 矩阵运算和 OpenCV resize/人脸 API 检查；
没有模型文件，不能声称实际检测、识别、麦克风、RKNN 或 NPU 推理通过。
NumPy 1.26.4、Torch 2.13.0、MediaPipe 0.10.18、protobuf 4.25.9 和 pydantic
2.13.5 留在 Vision 自己的环境；不与 Action NumPy 2.x 或 Voice 合并。
两个 OpenCV distribution 共用 cv2 的历史风险保留，当前功能探针通过，不擅自删依赖。

唯一源码修正是 setup.py 补装 config/fastdds.xml 和 scripts/fastdds_env.sh：
原 wheel 缺失、原 ROS CMake 已安装。修正先在候选副本验证，再按原样导入和单独修复。
算法、lock、默认配置、公开协议未改；最终清洁 wheel 资源 hash 全部匹配。

ROS 独立构建和已安装 mock 节点通过：合成 Image 输入、6 个 VisionTask 用例、
视觉事件字段与原仓相同。视觉发布端实际使用 BEST_EFFORT；测试订阅按 sensor_data
QoS 匹配。此事实需要进入平台接口清单，不能用 Reliable 订阅的收不到数据误判算法。
测试只使用独立 localhost domain/临时注册表，face API 和深度定位关闭。
RGA bridge 因本机无 librga 未编译；默认关闭的 DMA-BUF/RKNN 板端 probe 未开启。

运行：
```bash
uv sync --project modules/vision --locked --no-install-project --extra dev --extra models --python /usr/bin/python3.10
python3 -B tools/check_vision_tests.py
python3 -B tools/check_vision_install.py --uv uv
python3 -B tools/check_vision_ros.py --uv uv
```

前两个 ROS 相关命令依赖现有 Humble（tests 和 ros），wheel 命令不依赖 ROS。
CI 只运行 wheel CPU/资源和接口保护，完整 Humble 单测/传输为本机验证，不伪称 hosted CI。
生产数据和模型根路径需使用明确的 MARSDOG_VISION_PROJECT_DIR/MODEL_DIR/DATA_DIR，
不搬移原人脸数据。Lite3 本机统一启动采用独立开发 profile。
