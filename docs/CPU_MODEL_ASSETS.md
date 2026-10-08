# CPU 模型资产接入与实测 — 2026-09-29

用户提供 /home/elephant/MarsDog/models.zip，原文件保留。
CPU 资产已准备，真实推理已执行；**完整感知验收仍未通过**。
模型、公开样本、准备依赖保存在不提交的资产目录，Git 保存清单、工具与证据。
新准备默认使用仓库根 models；历史 out/models 资产保留。见 [目录规范](../config/models/README.md)。

## 可复现入口

在 WSL Ubuntu-22.04 主仓中：

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py models --model-archive /home/elephant/MarsDog/models.zip --download
python3 tools/marsdog.py replay --manifest models/cpu-20260929/cpu-replay.json
python3 tools/check_cpu_model_runtimes.py --assets models/cpu-20260929
~~~

第二条目前应返回 FAIL / exit 1：两张视觉正例没有检出 dog。不能把这个预期失败写成整体验收通过。
可以分别运行生成的 voice-replay.json 和 vision-replay.json；当前语音单独通过。
models 的 READY 仅代表资产准备完成，model_acceptance=false。

无需更新五个模块的 lock 或安装系统依赖。下载阶段要求网络；已有完整缓存时去掉
--download 可离线准备并核验。工具只支持本轮已有的 CPython 3.10 / Linux x86_64
Vision 环境；regex 准备依赖明确锁定此 ABI，不承诺在 Windows/ARM 原生运行。

资产目录默认 models/cpu-20260929，支持 MARSDOG_MODEL_DIR 根目录覆盖，也可用 --output 指定完整目录。
旧资产仍在 out/models/cpu-20260929，回放旧资产时显式使用其清单路径。指定的压缩包必须匹配
config/models/cpu-assets.lock.json，不能用另一个同名包绕过哈希。新模型更新需要修改
清单、复核来源和重做验收，已有不匹配文件会被拒绝而不会覆盖。

## 来源与 CPU 对应关系

| 能力 | 本轮 CPU 资产与来源 | 验证范围 / 限制 |
| --- | --- | --- |
| 物体检测 | 官方 YOLOE-26s-seg.pt + mobileclip2_b.ts；按包内 RKNN metadata.yaml 的原顺序生成 18 类提示 | 13 张 COCO128 猫/狗正例，11 PASS、2 FAIL；同系列同规模，原训练 checkpoint 和 NPU 数值等价性 UNKNOWN |
| ASR | 包内 SenseVoice int8 2024-07-17 ONNX + tokens；已有 CPU 权重无需重复下载 | 中文官方 ITN 样本回归 PASS；不是机器人口令/麦克风/整条 Voice 管线验收 |
| 人脸 | 包内 YuNet 2023mar、SFace 2021dec ONNX；原有 OpenCV CPU backend | 检测及 128 维有限非零特征 PASS；样本上有多余检测，不声明准确率/身份识别通过 |
| 姿态 | 包内 MediaPipe pose_landmarker_lite/full.task | 全身图像各检出 33 点姿态；这是原代码已有的 CPU 备选，不能称为 YOLOv8 RKNN 同权重转换 |
| 手部 | 包内 hand_landmarker.task，MediaPipe CPU | 能执行推理，黑图负例通过；照片未检出手，正例召回未验收 |
| VAD | 包内 silero_vad.onnx | 语音检出 1 段、2 秒静音检出 0 段；原 UploadedAudioVAD |
| 声纹 | 包内 3dspeaker CAMPPlus ONNX | 原 provider 提取/内存登记/同一录音自匹配通过，不证明不同录音的身份准确率 |
| KWS | 包内 Zipformer zh-en 3M 2025-12-20 CPU ONNX 三件套 + 原 kws_keywords.txt | 实际运行 40 个解码步骤；没有命中口令，不声明唤醒/关键词召回通过 |
| 意图分类 | 仅有 qwen2_5_5b_rk3588_260903_w8a8.rkllm | UNKNOWN：缺微调前 HF/PyTorch 权重、tokenizer 和训练记录；没有下载通用 Qwen 冒充原模型 |

包内的 YOLOE-26n 不是生产 26s 的同规模模型，因此没有悄悄替换成 n。
2025 SenseVoice、Paraformer、RTMPose、yolo26n、gesture_recognizer 等资产不自动改变生产选择。
未被本轮使用的文件保留在原包；提取的其他 CPU 文件不等于已验证的运行依赖。

原 RKNN 两份元数据都明确 end2end=false，派生 CPU checkpoint 也设为 false；
保留原置信度 0.2、IoU 0.2、图像尺寸 640 和类别顺序。
文本编码在准备进程完成，推理进程不需要 CLIP 或网络。
推理走原 ObjectDetectorProvider、ASRSherpaProvider；没有重写模型前后处理。

官方下载依据：
[Ultralytics YOLOE](https://docs.ultralytics.com/models/yoloe)，
[固定模型发布](https://github.com/ultralytics/assets/releases/tag/v8.4.0)，
[SenseVoice 官方样本参考](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)。
COCO128 ZIP 来自 Ultralytics assets v0.0.0；类别预期直接来自随包 annotation，
在本机第一次推理前固定，未根据模型输出改答案。它是小型训练子集，只用于类别存在性
回放，不能给出 mAP、完整 precision/recall 或泛化结论。

## 完整性与准备隔离

- models.zip 为 2,575,737,852 字节，SHA256
  6160bd0aa7944a22aa11ac024746930e2a2fa5e04b32f7e2c318db9d3c6785a6。
- 57 个选定包内资产逐文件固定 SHA256；原包内 NPU 权重与导出脚本不执行。
- 7 项在线资产固定 URL/大小/SHA256，包括 26s、文本编码器、COCO128、固定提交
  CLIP 源码与 ftfy/regex/wcwidth。模型两项摘要同时与 GitHub 官方 release API 对照。
- CLIP commit a13192f8cb767260d7dfd98c843b0716593169e7；相关源码、词表、许可及
  固定 wheel 只解包到 out/.../text-tools，只进入一次性准备子进程 PYTHONPATH。
  其 Torch/Ultralytics 仍取已锁定 Vision 环境，没有合并 Voice 环境。
- 模型准备拒绝路径越界、ZIP 链接/重复项、哈希或长度错误。先写临时文件、验证后发布，
  已有不匹配内容保留并报错。中断/超时回收本次子进程，不产生 READY。
- 下载中遇到过文本编码器尾部截断：253,768,122 字节，不匹配官方值，未被使用；
  从官方 URL Range 补回 26,354 字节，最终长度和 SHA256 均匹配，才接纳为模型。
- 派生模型的输入、标签、准备脚本、版本和输出哈希写入 yoloe-derivation.json；
  重复执行会核验并复用，不在验收中重新在线生成提示。

许可文本随可用归档保留。本轮没有将权重、COCO 图像或厂商模型重新发布到 Git/远端；
上游分发许可核对仍按现有第三方策略处理，不能据本轮本地测试推定可再分发。

## 实测结果与保留失败

完整回放目前是 FAIL，inference_executed=true，model_acceptance=false。

- 000000000307：COCO dog 正例，模型输出 dog frisbee toy / cat，缺 dog。
- 000000000394：COCO dog 正例，模型只输出 dog frisbee toy，缺 dog。
- 两图已经目视复核确实有狗，样本和预期不删除、不放宽阈值来制造通过。
- 语音中文参考通过；此样本不是动作命令，catalog_event=null 是合理结果。
- 辅助模型首轮半身图姿态正例失败也保留；另加事先目视确认的全身 bus 图后，
  lite/full 的 33 点姿态检查通过，不能据此声称半身输入也已修复。

真实模型揭示了汇总工具的问题：一个模块失败会跳过另一个模块，且丢失已执行的推理证据。
本轮只修正报告与调度：保留失败报告、继续其他独立模块、检查输入哈希，任一失败仍使
总体 FAIL。没有修改模块业务实现、ROS 类型或识别断言。

当前平台测试 27 项、旧契约 25 项、架构 DAG/接口检查和七原仓基线通过。
源码与完整失败/成功报告见 validation/cpu-model-assets；以前的冻结证据没有覆盖。

## 下一步

1. 保留这两张狗漏检为固定回归，用原 26s 导出前 checkpoint / 提示生成记录核对来源，
   再决定是否需要独立的 CPU 模型适配或质量优化；不把公开基础权重视作数值等价替换。
2. 提供原 RKLLM 微调前权重与 tokenizer，才能实现语义兼容的 CPU 意图推理。
3. 补充机器人实际录音（口令/否定/唤醒/噪声）及图像（玩具/人/手势）独立标注；
   在隔离 ROS 域验证真实事件/服务链路，再考虑可选真实感知启动 profile。
4. 相机/IMU/地图/SLAM 与 Lite3 硬件仍是独立验收范围。

现有 lite3-local-cpu 与 lite3-nav2-cpu 继续用感知 mock；本轮没有把未通过质量门禁的
模型接入默认机器人行为，也没有新建运控或嵌入式实现。
