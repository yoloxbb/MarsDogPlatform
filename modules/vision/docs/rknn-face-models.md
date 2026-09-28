# YuNet / SFace 的 ONNX 与 RKNN 切换

模型路径的扩展名自动选择推理实现：`.onnx` 使用 OpenCV，`.rknn` 使用 RKNN Lite。
没有 `backend` 配置，也不在模型失败时自动回退到其他文件。生产配置默认保留 ONNX。

## 切换配置

修改 `config/vision.yaml` 中三个模型路径，其他业务参数不变：

```yaml
providers:
  vision:
    type: observation
    enabled: true
    config:
      face_detect_model: ${MARSDOG_VISION_MODEL_DIR}/face_detection_yunet_2023mar_fp16.rknn
      face_recogn_model: ${MARSDOG_VISION_MODEL_DIR}/face_recognition_sface_2021dec_fp16.rknn
      # 可省略；当前角色各自默认使用下列已验证 profile。
      face_detect_rknn: {profile: yunet_2023mar_fp16, core_mask: "auto"}
      face_recogn_rknn: {profile: sface_2021dec_fp16, core_mask: "auto"}
  face_recognition:
    type: sface
    enabled: true
    config:
      face_recogn_model: ${MARSDOG_VISION_MODEL_DIR}/face_recognition_sface_2021dec_fp16.rknn
      face_recogn_rknn: {profile: sface_2021dec_fp16, core_mask: "auto"}
```

这是合并到现有配置的片段，不是完整配置文件。主视觉识别与独立任务识别均配置 SFace；
切换两者可以避免同一节点仍运行独立的 ONNX 人脸识别。YuNet 和 SFace 也支持混合格式。

模型目录依次采用 `MARSDOG_VISION_MODEL_DIR`、项目内 `models/vision`、项目同级
`models/vision`。模型不随 Python 包打包，部署时需要同步这些文件。

配置在节点重启后生效。使用既有启动入口：

```bash
ros2 launch marsdog_vision_interaction vision.launch.py config_path:=/absolute/path/to/vision.yaml
```

回退时将对应路径改回 `.onnx` 文件并重启。启动同步会从已有样本 JPG 重建内存特征，
无需改写原始样本。不要把不同模型/预处理产生的外部特征直接混入同一特征库。

## 当前支持的 RKNN 文件

第一阶段仅支持 RK3588 的两个已验证 FP16 导出。profile 绑定 SHA256，文件改名不影响
验证，但替换内容需要重新验证并更新 profile；仅把 INT8 文件改名为 FP16 不会被接受。

| Profile | SHA256 |
|---|---|
| `yunet_2023mar_fp16` | `bbdd709d9f3385c45e7bb4ac667609866d32f3e80767c1bb0a6c2b4b00e52315` |
| `sface_2021dec_fp16` | `42d25f58bf8af8673d040083ac4b8ae9697c2588e4d7b1c6ce3f25c5fdab87db` |

YuNet 采用 BGR、FP16、NHWC、pass-through 输入，编译尺寸为 640×640。输入图片等比例
缩放后在右侧/底部补零，检测框及五点关键点返回原图坐标。`setInputSize()` 表示原图尺寸，
不会重编译模型。640×480 图像只在底部补 160 像素。

SFace 的五点对齐保持与 OpenCV 一致，`feature()` 输入是 BGR 图片，由适配层转为
112×112 RGB、FP16、NHWC、pass-through，返回 128 维 float32 特征。模型图内已有
归一化，不在独立 Provider 重复执行 `(pixel-127.5)/128`。这一修正也适用于独立 ONNX
路径，需使用实际同人/异人样本复核其 `match_threshold`。连续识别与独立识别分别使用
现有 `sface_cosine_threshold` 和 `match_threshold`，本次不调整阈值。

## Runtime 与故障定位

RKNN 依赖 `rknn-toolkit-lite2` 和匹配的 `librknnrt.so`、NPU 驱动；ONNX 模式无需导入
RKNN。人脸与物体检测复用 runtime 库定位：Provider 的 `rknn_runtime_library`、环境变量
`MARSDOG_RKNN_RUNTIME_LIBRARY`、rknnlite 包旁库文件、系统 `/usr/lib/librknnrt.so`。
一个进程必须使用同一个 runtime 库；冲突配置会明确报错。

`core_mask` 可选值为字符串 `"auto"`、`"0"`、`"1"`、`"2"`、`"0_1"`、`"0_1_2"`；
配置文件中请保留引号，避免 YAML 将带下划线的值解析成数字。数字 `0`、`1`、`2` 仍分别
表示三个独立核心，数字 `3`、`7` 和其他未列出的值会被拒绝。

RKNN Lite 2.3.2 导入时会重置 Python logging 的标准级别名称。项目 runtime helper 会在
导入期间保存并恢复这些名称，避免之后加载 Ultralytics/Torch 时出现 `Unknown level:
'WARNING'`。这也是为什么 RKNN runtime 必须通过项目工厂初始化。

启动日志标明实际模型实现、profile 和加载结果。YuNet/SFace 部分失败时会单独输出错误，
不会因为 Pose/Hand 成功就隐藏人脸模型故障。未知扩展名、未知 profile、指纹不匹配、
运行时加载失败都不会改用其他模型。静态模型可能打印动态尺寸查询警告；以实际加载、
推理结果判断状态。

共享 YuNet 的录入操作继续使用节点已有的推理互斥锁。模型停止时先等待推理线程，再释放
RKNN 实例；独立识别也串行保护模型加载、推理和释放。

## 验证

不依赖硬件的回归测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

禁用插件自动加载是为了避免本机 ROS pytest 插件引入无关依赖；项目自身 `conftest.py`
仍会正常加载。

RK3588 上对照已有本地图片；命令只读取样本，报告不包含图片或特征向量：

```bash
.venv/bin/python tools/check_face_rknn.py --iterations 50 --report /tmp/face-rknn-report.json
.venv/bin/python tools/check_face_rknn.py --iterations 50 --with-pipeline --report /tmp/face-rknn-pipeline.json
```

第二条同时运行实际 Pose/Hand/跟踪链路和另一线程上的 YOLOE。使用重复静态图片，只能
证明这些配置能共同执行及短期稳定性，不代替真实视频的精度评估、长时间运行测试或误识率
验收。报告中的同裁剪特征相似度阈值是数值对照检查，不是身份识别阈值。

若 RKNN 推理返回异常或不符合 profile 输出契约，适配层会立即释放 runtime；Provider 会
将对应 YuNet/SFace 状态置为 unavailable 并跳过后续调用，检测路径同步缺失 track，识别
路径返回 unknown。普通坏帧和单次对齐失败仍沿用原有的空结果/ROI fallback。
