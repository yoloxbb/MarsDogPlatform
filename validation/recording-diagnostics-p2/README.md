# P0–P2 验收：录音、决策诊断、能力清单与功能草稿

日期：2026-10-03。分支 feature/recording-diagnostics-p2，从 90b16be 继续；
开始时工作区干净，中断恢复时保留全部未提交改动。
最终代码和报告哈希见 [summary.json](summary.json)，提交版本以本目录所在 Git 提交为准。

## 完成内容

- P0：新增任意合规 WAV 的真实 CPU ASR → 安装后 Voice → DDS → BT → Action 试用。
  生成离线 HTML/JSON 时间线，关联 ASR、事件、候选、等待/仲裁、取消、Goal 和终态。
  BT 诊断显式开启，默认关闭，失败不参与业务决策。
- P1：由原始定义及 Action 自身 Lite3 策略生成能力清单；增加完整 BT/Action 的五项
  DDS 场景。没有补造缺失动作，没有把配置 verified 当成本次硬件验收。
- P2：新增功能草稿生成及校验，包含配置落点、Voice/BT/Action 契约模板和六类验收项。
  草稿未激活；未知模板、命名冲突、错误字段类型和覆盖已有目录会被拒绝。
- 文档和手动 Humble CI job 已更新；沒有远端 CI 运行记录。

入口：[录音试用](../../docs/development/RECORDING_TRIAL.md)、
[能力与功能开发](../../docs/development/FEATURE_WORKFLOW.md)、
[诊断字段](../../interfaces/application/decision-trace-v1/README.md)。

## 最终本地验证

| 检查 | 结果 |
| --- | --- |
| dev.py check | 106 平台测试通过；架构及命名门禁通过，既有缺口单列 |
| Behavior | 538 通过，0 跳过 |
| Voice Humble | 430 通过，0 跳过 |
| Emotion | 374 通过（含原 subtests），0 跳过 |
| Action | 429 通过，29 既有跳过；PySide2 / 未装 rclpy 的纯测试范围限制 |
| Action Humble 回调 | 35 通过，0 跳过；与纯测试部分重叠 |
| 声音 / 视觉 / 状态 | 46 / 33 / 34 固定契约通过 |
| 任务 / 结果 | VoiceTask 18、VisionTask 18；结果契约 25 通过 |
| 五模块 wheel | 全部通过，新诊断/能力组件纳入安装来源与源码哈希检查（合计 20 组件） |
| ROS | 15 包 build、doctor、默认 smoke、取消 transport、SIGINT/SIGTERM shutdown、supervisor lifecycle 通过 |
| 完整 BT/Action 仲裁 | 五场景通过，四组件正常回收，无强杀，无硬件 Topic 发布者 |
| 原 CPU flow | --acceptance flow --with-behavior 通过；模型精度验收仍为 false |
| 两条 WAV trial | 合成“回家”到模拟导航 SUCCESS；合成“坐下”保留策略拒绝，均符合显式预期 |
| 草稿模板 | 新草稿 Voice/BT 正向测试按预期失败；复用 Action 检查通过。绑定已有 SIT 路由的模板对照 Voice 2 / BT 2 / Action 1 全通过 |
| 工作区检查 | git diff --check 通过；生产 YAML/profile、IDL、依赖锁与历史契约基线未改 |

未修改 Vision 运行代码，本轮未重跑其完整单测；Vision 的 wheel、视觉/任务契约和
安装后的模拟节点参与验证。当前完整单测历史记录仍在前轮验收中，不改写其 RGA 跳过项。

五个新增场景：重复事件仅一个 Goal、同级命令等前一终态、STOP 抢占后旧 Goal 先终结、
陈旧视觉目标下发前拒绝、命令完成后 Needs 先于 Emotion。
移动目标丢失/不切换干扰人的原 Action 回归随全量单测通过；不将陈旧样例描述为真实相机断流。

录音 trial 要求真实 ASR 一次、文本注入零次，Goal 与终态逐个匹配，
会话与语句匹配，所有组件正常关闭。报告区分“检查符合预期”和“动作执行成功”。
例如坐下实际返回：

~~~text
outcome: action_failed_or_canceled
status: FAILURE
reason: lite3_action_gated:unit_id=ACT_BASIC_SIT,fidelity=proxy,verified=False
~~~

## 证据与范围

原始日志保留在 out/p0p2。最终录音报告：

- out/p0p2/trial-home-final/20261003T150358774501Z/report.html
- out/p0p2/trial-sit-final/20261003T150414241912Z/report.html
- out/p0p2/decision-final/20261003T150220422693Z/result.json
- out/p0p2/cpu-flow/20261003T150219465126Z/result.json

WAV 为本机 Microsoft Huihui Desktop 合成中文语音；ASR 实际处理波形，没有用文本绕过。
合成录音不等于用户麦克风验证；没有硬件、VAD、声纹或模型精度验收。
底盘、视觉和导航为开发替身，生产门限、取消归属和需求结算不变。

能力清单保持 125 条声明式路由、82 条词库命令、74 个模板、183 个 Unit；
49 条路由引用缺失模板照实保留。草稿 NOT_RUN 不计作已实现功能的验收。
导航/避障内部实现、模型调优、旧迁移基线、旧源码包及主线标签均未改。
