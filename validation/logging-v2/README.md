# 日志系统 v2 重构验收

日期：2026-10-04（Asia/Shanghai）。主仓 marsdog-platform，分支 refactor/unified-logging。
起点 487a1b2，开始时工作区干净；此前的兼容日志重构保存在原提交和 validation/unified-logging。
用户明确授权放弃旧日志格式。本轮完成公共包 0.2.0 / envelope v2，未修改业务协议、生产配置、
模型参数、动作证据门限、需求结算或导航/避障内部实现。历史日志未删除或改写。

## 实现

- 每进程一个有界异步 JSONL 写入器，普通诊断、事件、生命周期、耗时共用协议。
  终端、查询和 HTML 从同一数据展示；模块不再维护 TRACE、BT JSON 或决策文件写入器。
- context 保存原有关联身份，fields 保存领域属性；显式 LoggerAdapter 不修改全局 Logger 类。
  标准 Python 异常堆栈与调用位置保留。ROS 原生 once/throttle 通过独立 rosout 适配器保留。
- Action 正式执行入口产生唯一 execution.completed；异常产生 execution.crashed 后原样抛出。
  原 debug 发布器不再负责日志记录。反馈/取消/接受日志保留原执行结果。
- 明确 lifecycle 优先队列、采样和重复状态合并；文件按 UTF-8 字节轮转。
  修复业务 need_level 与日志 level 冲突，以及满队列误抑制重试的问题。
- 查询、录音报告、视觉耗时工具已切换到 v2。旧格式 reader 不再支持；历史文档明确标记。

## 验证

| 门禁 | 结果 |
| --- | --- |
| dev.py check | 架构/命名检查、115 项平台测试、13 项公共日志测试通过 |
| Voice 全量 Humble 单测 | 430 通过 |
| Vision 全量单测 | 294 通过，3 项显式硬件跳过 |
| Emotion 全量单测 | 374 个 JUnit 条目通过（包含子测试，不与其他模块相加） |
| Behavior 全量单测 | 538 通过 |
| Action 纯单测 | 429 通过，31 项缺 ROS 跳过 |
| Action 实际 Humble 回调 | 37 通过，0 跳过；含新增唯一终态、上下文和异常传播测试 |
| 五模块 wheel | 全部通过；隔离导入、组件源码哈希、包资源检查 |
| 原声音/视觉/状态契约 | 46 / 33 / 34 场景通过 |
| 感知任务契约 | Voice、Vision 各 18 场景通过，原生成 ROS 类型 |
| Action→BT→Needs 结果契约 | 25 通过 |
| build / doctor / smoke | 16 包构建、环境核验、安装节点 DDS 链路通过 |
| 监督生命周期 | 中断、业务子进程故障、日志收集器故障三项通过，子进程全部回收 |
| 原生 ROS 日志 | once/throttle、源位置、无循环及退出落盘通过 |
| Action DDS / shutdown | 真实传输通过；SIGINT、SIGTERM 两项通过 |
| 仲裁 / 感知恢复 | 5 / 7 场景通过 |

公共测试包含：满队列不等待 sink、优先队列、磁盘失败、UTF-8 轮转、超大记录、
线程/async 上下文隔离、重启身份、重复状态、失败重试、异常堆栈、真实调用位置、动态级别和禁用写入。
故障注入中的预期 FAIL 文本不代表验收失败；对应测试检查 fail-closed/进程回收。

## ASR 到动作和日志审计

| 运行 | 实际结果 | 统一记录数 |
| --- | --- | ---: |
| trial-home | 真实 CPU ASR“回家”→EVT_VOICE_COMMAND_GO_HOME→go_home SUCCESS | 915 |
| trial-sit | 真实 CPU ASR“坐下”→sit_down FAILURE；原 lite3_action_gated 门限拒绝 | 759 |
| cpu-flow | 软件链路通过；1 个真实 ASR、7 个明确文本夹具 | 2801 |

三次运行均覆盖 voice / vision / emotion / behavior / action / ros，共 9 个进程实例，
每次只有一个 run_id。所有健康文件 closed=true、pending=0，dropped、priority_dropped、
sink_errors、oversized 均为 0。每个已记录完成的 Goal 只有一条 action.execution.completed；
语句身份可关联 Voice→Behavior→Action，CLI 按 Goal/kind 查询验证通过。
不存在新的旧 TRACE/decision 文件，context 身份不在 fields 重复。

“回家”“坐下”使用之前生成的 Microsoft Huihui 合成 WAV；这是真实模型计算与模拟设备的集成检查，
不是用户录音、实体机器狗、麦克风、NPU 或模型精度验收。所有报告 model_acceptance=false。

机器可读证据索引、报告哈希和运行目录见 [summary.json](summary.json)。
源码指纹为 `681f5331999808d2348708230698c290fec142a015065551cb59f49376a717a4`，
构建、三次完整运行和审计时一致。原始本机证据在 out/logging-v2，安装报告在 out/*-install，
smoke/生命周期报告路径也保存在索引中。out 为可重建本机产物，不提交庞大日志。

## 复现入口

在已准备的 Humble/CPU 环境、主仓根目录执行：

```bash
python3 tools/dev.py check
python3 tools/marsdog.py build
python3 tools/marsdog.py smoke
python3 tools/check_logging_runtime.py
python3 tools/marsdog.py trial --wav out/p0p2/fixtures/go-home.wav --expect-event EVT_VOICE_COMMAND_GO_HOME --expect-outcome success --output out/my-log-trial
python3 tools/marsdog.py logs --run RUN_DIRECTORY --component action --kind lifecycle
python3 tools/marsdog.py logs --run RUN_DIRECTORY --health
```

其余验证入口和适用范围见 [工程门禁](../../docs/development/WORKFLOW.md)。
配置、协议和新功能日志写法见 [统一日志指南](../../docs/development/UNIFIED_LOGGING.md)。
