# CPU 感知回放基础设施验收

2026-09-29。当前状态 SOFTWARE_READY_AWAITING_MODEL_ASSETS。
model_acceptance=false：没有实际权重、标注图像或命令录音，因此没有声称模型推理通过。

已验收软件范围：
- 独立 Voice/Vision replay 入口、哈希与标注清单、CPU 参数透传、失败报告。
- 平台19项工具测试（含此前6项），含真实子进程 SIGINT/SIGTERM 回收。
- Vision 289 passed / 3 RGA skipped；Voice 380 passed。
- 两个独立 wheel 的资源、replay 模块哈希及 CLI 验证。
- ROS 重建、默认和真实 Nav2 profile 的原有 mock 感知全链路兼容性。
- 25项既有契约、15 ROS manifests/21接口、原仓与旧报告哈希核对。

模块新增单元测试使用明确的模型替身，不是实测模型准确率。
missing-assets.json 是通过统一 CLI 得到的实际未验收结果（exit 2），不是测试失败被改写。
asset-audit.json 记录搜索范围与所需资产。platform-tests.txt 中测试构造的 FAIL/BLOCKED
用于检查拒绝路径，不应当作真实模型运行结果。报告中的临时安装目录已由工具清理，
保留的是当时的安装观察与哈希；可按说明重新创建验证。

范围与命令见 ../../docs/CPU_PERCEPTION_REPLAY.md。
原始模型、录音、图像不进入主仓；本轮没有下载任意权重或更改 Python 依赖锁/ROS IDL。
