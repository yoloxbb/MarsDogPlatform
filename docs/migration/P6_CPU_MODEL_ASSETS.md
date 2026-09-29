# P6 增量：CPU 模型资产与首轮真实推理

接收用户 models.zip，保留原文件和原仓。已实现统一 models 命令、固定资产清单、
模块自有 YOLOE 18 类 CPU 准备工具、辅助模型运行检查。
完整步骤、来源、替代边界及风险见 ../CPU_MODEL_ASSETS.md。

实际交付为 CPU 资产和真实回放证据，不能标为完整模型验收通过：
YOLOE 13 张正例 11 PASS / 2 FAIL；SenseVoice 中文官方参考 PASS；
辅助 face/pose/hand/VAD/speaker/KWS 运行探测在明确范围内完成。
RKLLM 微调原权重 UNKNOWN；已有两个本机 profile 没有切换真实感知。

本轮没有改业务 provider、生产 YAML、IDL、模块 uv.lock、ROS 构建与原仓；
新增代码只在工具、准备/验证脚本和测试。回放汇总修复确保失败推理不丢证据，
一个模块失败仍会验证另一模块，整体失败仍 exit 1。

平台工具 27 tests、契约 25 tests、架构 15 ROS manifests / 21 interfaces、
七原仓基线检查通过。无需 ROS 重建：没有改被安装的业务 package 或 ROS 源文件。

证据冻结到 validation/cpu-model-assets，包括第一次回放失败、修复后的完整汇总、
姿态首轮失败与补充全身样本结果、模型派生/缓存复用、测试和原始基线记录。
模型和公开样本二进制留在 out，不入主仓历史。
