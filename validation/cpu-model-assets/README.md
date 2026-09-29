# CPU 模型资产冻结证据

本目录对应 release-manifest.json 的源码提交；不是全模型 PASS。
replay/result.json 保留实际视觉 11/13、语音通过及总体 FAIL。
aux 是各自注明范围的运行探测，不是识别准确率报告。
initial-development-runs 保留开发期间首轮半身姿态失败、旧汇总工具漏记推理/跳过语音的报告；
这些早期报告不对应最终修复后的完整工具源码，不能用于宣称当前整体通过。
checks 包括 27 平台测试、25 契约、架构与七原仓基线。
模型二进制和标注图像不在此目录，使用 config/models/cpu-assets.lock.json 与 models 命令复现。
