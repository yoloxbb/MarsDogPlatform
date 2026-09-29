# P6 CPU 感知回放基础设施

2026-09-29。已交付统一 replay 命令与模块内离线 CPU 入口。
状态为 SOFTWARE_READY_AWAITING_MODEL_ASSETS；没有实际模型精度通过记录。

改动：
- tools/marsdog.py replay → tools/check_perception_replay.py。
- modules/vision/marsdog_vision_interaction/replay.py 复用原物体检测 provider。
- modules/voice/marsdog_voice_interaction/replay.py 复用原 ASR、WAV 解码和精确词库。
- 两 provider 只增加可选 CPU 参数；没有修改模型算法或默认 YAML。
- 有格式/哈希/独立标注/超时/子进程失败门禁；模型缺失返回退出码 2。
- 现有 wheel 门禁增加新模块内容与 CLI 检查；CI 继续使用独立模块环境。
- 没有新增依赖、合并锁文件、改变 ROS IDL 或移动历史代码。

实际验证：Vision 289 pass / 3 RGA skip；Voice 380 pass；平台 19 项；
现有 25 项契约、15 ROS manifests / 21 接口检查通过。独立 wheel、ROS 构建、
两套开发 profile smoke 均通过。这些计数不能冒充实际模型推理用例数。

当前没有提供可用的 CPU 模型或带答案的感知样本，模板实际执行结果是
BLOCKED_MISSING_ASSETS，model_acceptance=false。输入资产需求、搜索范围与限制
见 validation/perception-replay/asset-audit.json。没有下载任意权重或将媒体展示资源
当作已标注感知数据。缺资产期间不启用生产麦克风/相机/串口，也不改变 Voice 的
原生产回退策略。详见 ../CPU_PERCEPTION_REPLAY.md。

自审：平台只编排与存证，业务留在模块；无新循环依赖/业务 common；小范围参数透传
保留默认行为；未重新实现识别算法。此切片仅物体检测、已切分语音和精确词库，
更完整的感知管线/ROS时序需要真实模型和样本后继续验收。

后续会话先读取最新状态与本文件，再核对真实资产清单。不要因为存在模板或
单元测试 PASS 就将模型精度、实时性能、NPU 或实机状态标为完成。
