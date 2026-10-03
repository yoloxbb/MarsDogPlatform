# 录音 → ASR → 行为 → 动作试用

在主仓根目录运行。该入口使用真实 SenseVoice CPU ASR、现有 Qwen CPU 意图/词库路径，
启动安装后的 Voice、BT、Action、Needs 等节点，通过 localhost DDS 通信。
输入是一段已切分 WAV，视觉、Lite3 和导航使用开发环境替身。它不读取麦克风，
不绕过动作能力门限，也不修改默认 profile。

## 准备与启动

先按 [CPU 软件流程](../CPU_SOFTWARE_FLOW.md) 和 [模型资产](../CPU_MODEL_ASSETS.md)
准备已有 CPU 环境与模型。Voice 同步环境时保留 `--intent-cpu`。
源码变化后重新 build；工具会拒绝源码与安装不一致的试用。

~~~bash
python3 -B tools/marsdog.py build
python3 -B tools/marsdog.py trial --wav /absolute/path/command.wav --check-only
python3 -B tools/marsdog.py trial --wav /absolute/path/command.wav
~~~

WAV 必须是 16 kHz、单声道、16-bit PCM，非空且不超过 60 秒 / 20 MiB。
输入应包含一句清晰命令；不自动重采样或去掉否定词。仅检查格式不检查模型/ROS 是否就绪。

可以给出可验证的预期：

~~~bash
python3 -B tools/marsdog.py trial \
  --wav /absolute/path/go-home.wav \
  --expect-event EVT_VOICE_COMMAND_GO_HOME \
  --expect-outcome success
~~~

可选参数：

| 参数 | 用途 |
| --- | --- |
| --voice-manifest / --intent-manifest | 指向已验证的 CPU 模型清单；默认使用本机已有 out/models 路径 |
| --output | 输出根目录；每次新建带时间戳的子目录 |
| --terminal-timeout | 等待 Action 终态，默认 75 秒，允许 1–180 秒 |
| --timeout | 整组观察超时，默认 300 秒，允许 30–600 秒 |

模型清单仍包含固定官方普通话样本，以复用既有资产校验；trial 实际只投递指定 WAV，
不会把该样本或文本命令作为另一次输入。不联网下载模型，不做模型精度优化。

工具独占 localhost ROS domain 215，与原 voice-cpu-ros 测试串行运行。
它自行启动和关闭进程，无需先运行 `marsdog.py up`。
按 Ctrl-C 可中止，退出清理仍执行；失败日志和报告保留。

## 如何读结果

终端打印本次目录；打开目录中的 `report.html`，无需网络。
同目录的 `result.json` 为验收结果，`trace.json` 为合并时间线，
`decisions/*.jsonl` 为 BT 原始诊断，组件日志用于进一步定位。
报告按 interaction_id、utterance_id、candidate/goal_id 关联，不能只凭行为名称拼接两次请求。

| outcome | 含义 |
| --- | --- |
| success | 已观察到对应 Goal，并收到 SUCCESS 终态 |
| action_failed_or_canceled | 已下发 Goal，终态为失败/取消/中断等 |
| rejected_before_goal | 语音提出执行请求，BT 在下发前拒绝，报告含关联拒绝记录 |
| no_dispatch_requested | 实际语义事件未提出执行请求，例如普通对话或否定表达 |

`status=PASS` 表示试用证据完整且显式预期匹配，不代表每次动作都成功。
例如“坐下”可能识别正确并到达 Action，然后被原有
`lite3_action_gated: ACT_BASIC_SIT` 门限拒绝；应查看 outcome 和终态原因。
缺少终态、错会话、文本注入、ASR 错误、组件异常退出均不能算通过。
模型验收和硬件验收始终单独标为未完成。

时间线含 ASR 开始/结束、语义事件、候选生成/排队/等待/选择、仲裁、
取消请求、Action 接受/终态和 BT 终态。重复等待原因合并，原因变化仍记录。
ASR 毫秒数是预切分音频的处理耗时，不包含录音/VAD，不代表实机整段交互延迟。
部分唤醒专用分支仅有原节点日志；不能把缺少某条诊断当作该动作没有发生。
诊断格式见 [decision trace v1](../../interfaces/application/decision-trace-v1/README.md)。

## 已验证范围

2026-09-30 的本机合成“回家”WAV 经真实 ASR → Voice → BT → Action 完成模拟导航；
合成“坐下”WAV 正确显示原 Lite3 策略拒绝。最终回归结果见
[本轮验收](../../validation/recording-diagnostics-p2/README.md)。

合成语音不是用户录音；试用入口可接收用户 WAV，但未宣称用户麦克风、VAD、
声纹、真实相机、真实底盘或模型精度验收通过。原来的固定 CPU 流程继续保留。
