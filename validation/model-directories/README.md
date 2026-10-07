# 统一模型目录验证 — 2026-10-07

基于 main 387792e，开始修改前工作区干净。默认模型根改为平台仓库 models，
支持 MARSDOG_MODEL_DIR 绝对路径覆盖，保留 Vision 专用目录覆盖。
Voice 只改变模型路径，词库、SDK、存储、ROS 协议与推理配置沿用原逻辑。
CPU 准备默认写入新目录；已有 out/models 资产原样保留，试用入口按明确规则兼容读取。

| 验证 | 结果 |
| --- | --- |
| 架构 / 标识检查 | 无新增错误，既有标识缺口保留 |
| 平台工具 / 日志基础设施 | 120 / 13 通过 |
| Voice Humble 单测 | 438 通过，无跳过 |
| Vision 单测 | 302 通过，3 项 RGA 库检查跳过 |
| Voice / Vision wheel | 均通过；验证默认安装路径、统一根覆盖、Vision 专用覆盖 |
| ROS 构建 / doctor | 通过 |
| 默认 smoke | 通过，设备替身 |
| 生命周期 | 停止、业务子进程崩溃、日志采集进程崩溃三项通过，无遗留进程 |
| 真实 CPU ASR 回家录音 | PASS，ASR 文本“回家”，GO_HOME 事件到模拟动作 success |

路径回归覆盖重新命名的 checkout、源码与 out 下安装配置、任意 cwd、外部配置、
外部模型根、脱离仓库安装缺少根目录时报错、显式模型路径、CPU 旧目录兼容和新包不完整时拒绝回退。
根 .gitignore 忽略模型权重，仅提交 models/README.md。

[结果与源码/原始报告摘要](result.json)记录构建指纹、测试数量及旧资产哈希。
原始报告保存在 out/model-directories；本次没有下载、重提取、转换或优化模型。
模型精度、真实摄像头、NPU 和实机动作均未验收。远端 CI 未在本次本地修改中运行。

规范与使用方式见 [config/models/README.md](../../config/models/README.md)。
