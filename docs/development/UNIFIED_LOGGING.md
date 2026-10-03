# 统一日志：运行、查询与扩展

五模块使用 `marsdog-observability==0.2.0`，以 envelope v2 JSONL 作为唯一项目日志格式。
普通诊断、业务事件、生命周期和耗时统一进入每进程一个异步写入器；终端与 HTML 是日志的展示视图。
原 VOICE_TRACE、VISION_TRACE、BT JSON 和 decision-trace 文件写入器已移除。
历史文件保持原样，新查询工具只读取 v2；本次变更不兼容旧日志解析器。
ROS 类型、话题、业务事件、动作门限、取消和需求结算未因此改变。

## 启动和查询

从主仓根目录执行；已有环境不需要重装模型：

```bash
python3 tools/marsdog.py build
python3 tools/marsdog.py up
# 另一终端
python3 tools/marsdog.py logs --run latest --limit 50
python3 tools/marsdog.py logs --run latest --component action --kind lifecycle
python3 tools/marsdog.py logs --run latest --level warning
python3 tools/marsdog.py logs --run latest --event behavior.
python3 tools/marsdog.py logs --run latest --goal YOUR_GOAL_ID --json
python3 tools/marsdog.py logs --run latest --health
```

`latest` 指 out/local/latest-run.json 所指组合运行，包括失败运行。
录音试用应使用返回的具体 run_directory：

```bash
python3 tools/marsdog.py trial --wav /absolute/path/command.wav --output out/my-trial
python3 tools/marsdog.py logs --run out/my-trial/RUN_DIRECTORY --interaction INTERACTION_ID --utterance UTTERANCE_ID --json
```

会话查询先按 interaction/utterance 匹配，再通过已有 candidate/behavior/goal ID 关联下游。
明确属于其他会话的记录不会混入。ROS 普通文本通常不含业务 ID，可补充按模块查看。
`--event` 匹配名称前缀，`--level` 是最低严重级别，`--kind` 精确筛选类别。
默认返回筛选后最近 100 条；最多扫描两遍文件，只保留相关身份和最后 N 条记录。
损坏或旧版记录报告文件/行号（最多 1000 项）并使命令非零退出，不妨碍读取其他有效行。

## 协议和记录责任

完整字段定义见 [envelope v2](../../interfaces/observability/README.md)。
每条记录包含 timestamp、monotonic_ns、run_id、component、instance_id、pid、host、sequence、
level、kind、event_name、logger、message、context、fields。source 与 exception 按需出现。
`context` 专门存放已有的会话/语句/候选/Goal/目标身份，`fields` 存放领域属性。
同一字段不再同时复制到顶层、message 和 fields。嵌套业务 payload 仍保留原协议含义。

| kind | 用途 | 示例 |
| --- | --- | --- |
| event | 业务状态变化或观察 | voice.event.published、behavior.candidate.created |
| lifecycle | 启停、Goal 边界和终态，使用预留队列 | runtime.started、action.execution.completed |
| diagnostic | 普通日志和 BT 内部节点细节 | log.message、ros.message、behavior.internal.* |
| metric | 阶段耗时观察 | vision.stage.completed |

| 模块 | 负责记录的内容 |
| --- | --- |
| Voice | providers.ready、interaction.started/ended、stage.started/completed、event.published、utterance.completed；意图工作线程传播上下文 |
| Vision | providers.ready/stopped、stage.completed、event.published/cleared/suppressed；保留阶段采样策略和失败直报 |
| Behavior | 候选入队/拒绝、等待理由、仲裁、Goal 派发/接受、BT/Action 终态；内部树节点细节为 DEBUG |
| Action | goal.responded、cancel.responded、execution.started/completed/crashed、stage.feedback；从正式回调观察 |
| Emotion | 信号发布与行为结果处理；多个节点各自拥有 instance_id 和文件 |
| ROS | 独立 /rosout 收集器，保留源位置、时间和 source_component；不包装 RcutilsLogger |

Action 每次正常返回的执行回调只产生一条 `action.execution.completed`，包括验证失败、忙和取消返回。
未处理异常记录 `action.execution.crashed` 和堆栈，随后原样抛出，不伪造 Action Result。
原 debug 话题继续用于接口观察，但不再另写一份终态日志。
这些记录仍不能替代正式 DDS/Action 结果或 Needs 的结算证据。

日志严重级别与 kind 独立：INFO 记录关键状态，DEBUG 记录内部细节/候选抑制，WARNING 记录拒绝或降级，
ERROR 记录异常。不要以事件名包含 result/terminal 等字符串来决定写入优先级。
高频帧/波形/周期状态全文不应逐条放 INFO；重复等待通过 repeat_key 合并，理由变化会再次记录。
队列满而未成功入队的记录不会抑制后续重试。

## 文件与 ROS 适配

```text
RUN_DIRECTORY/
  log-manifest.json                  # run_id、schema、归属、active/closed
  structured/
    voice-<instance>.jsonl           # 每个进程一个流；包括诊断和业务观察
    voice-<instance>.jsonl.1         # 最近期轮转备份
    voice-<instance>.health.json
    ros-<instance>.jsonl
  voice.log / action.log / …         # 启动器捕获 stdout/stderr，包括启动早期失败
  ros-log/                          # ROS 原生运行产物
```

启动器给所有进程分配同一 run_id 和 structured 目录，每个进程使用随机 instance_id。
因此重启不会覆盖前一进程的记录，多实例也不争用文件。独立相机进程遵循同一规则。
组合启动默认关闭项目终端视图，避免把完整 JSONL 再复制到 stdout 文件；bootstrap、第三方直接
print 和 ROS 原生输出仍可出现在原生文件中。它们由各运行时管理，不属于第二套项目日志 API。

ROS 收集器禁用自身 rosout，避免采集循环，保留原生 once/throttle 和源调用位置。
其 component 为 ros，fields.source_component 标识原节点所属模块；未知节点标为 external。
导航/避障内部未改写；已有 rosout 可按外部日志读取。收集器失败只标记 logging_degraded，
不停止业务进程。其他业务进程失败仍按原监督策略处理。

手动启动时，在已 source Humble/本仓安装的环境中为相关进程设置共同身份，并另起收集器：

```bash
export MARSDOG_RUN_ID=manual-20261004
export MARSDOG_LOG_DIR=/absolute/path/my-run/structured
python3 -c 'from marsdog_observability.ros import main; main()'
```

手动启动不会生成运行归属清单，默认清理工具不处理该目录。

## 配置、容量和故障

环境变量统一控制基础设施，不需要修改生产 YAML。旧 logging.console/file 不再创建本地写入器；
节点原 log_dir/log_level 参数继续作为默认值。Vision event_trace 和 timing_trace_interval_sec
仅控制领域观察的启用与采样，不负责输出格式或路径。

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| MARSDOG_LOG_LEVEL | 节点级别，通常 INFO | DEBUG / INFO / WARN / WARNING / ERROR / FATAL / CRITICAL |
| MARSDOG_LOG_CONSOLE | 独立终端自动开启；组合启动为 0 | 1 开启 stderr 人类可读视图，0 关闭 |
| MARSDOG_RUN_ID | 组合启动统一分配；独立启动 UUID | 一次运行身份 |
| MARSDOG_LOG_DIR | 节点 log_dir/structured | 组合启动自动指向本次运行 |
| MARSDOG_LOG_QUEUE_SIZE | 1024 | 普通队列，范围 8–8192 |
| MARSDOG_LOG_PRIORITY_QUEUE_SIZE | 128 | lifecycle 与 WARNING 以上预留队列，范围 8–1024 |
| MARSDOG_LOG_MAX_BYTES | 20971520 | 单文件 UTF-8 字节上限，范围 4096–104857600 |
| MARSDOG_LOG_BACKUPS | 4 | 备份数，范围 1–20 |
| MARSDOG_LOG_DISABLED | 未设置 | 1 禁用公共日志写入；业务与原生 ROS 不受影响 |

默认每个进程最多约 100 MiB，单条最多 16 KiB。文本/集合/嵌套深度均有上限；超大记录以
record_size_limit 占位并尽量保留截短后的身份。序列化在调用线程完成，文件和终端写入在后台线程完成。
普通和重要队列都可能丢弃；绝不为等待日志落盘阻塞业务。关闭时最多等待 3 秒排空。

健康文件约 5 秒更新一次，正常关闭再次写入：written、dropped、priority_dropped、sink_errors、
oversized、coalesced、pending、writer_alive、closed。降级提示最多每 30 秒输出一次。
磁盘不可写、SIGKILL、断电或文件系统卡住时不保证最后几条落盘或最终健康文件更新。
优先队列可能使文件行顺序不同于生成顺序；使用时间与 instance_id/sequence 还原观察顺序。

敏感键 password、authorization、api_key、access_token、refresh_token 自动遮盖；
普通 message 和 ASR 文本不自动脱敏。分享时按实际内容筛选。

跨运行清理是显式操作，默认只打印计划：

```bash
python3 tools/marsdog.py logs --prune --keep-runs 20 --max-total-mb 1024
# 确认计划后，使用同一命令追加 --apply
```

只处理有效 log-manifest 中已关闭的受管日志，最近运行优先保留。
运行中日志计入预算但不删除；超额单独报告。WAV、模型、配置、数据库、result.json、HTML 和
未登记历史目录保留。日志轮转不限制系统 journal、ROS 文件或任意外部 tee 文件的累计容量。

## 新功能如何接入

业务模块仅依赖公共包，不 import 另一模块内部实现；公共包只用标准库，不承载业务路由。
入口调用 configure，领域代码持有显式 LoggerAdapter，无全局 Logger 类替换：

```python
from marsdog_observability import configure, get_logger, bind_context, wrap_context

configure("voice")
log = get_logger(__name__).bind(area="speech_pipeline")
with bind_context(interaction_id=session_id, utterance_id=utterance_id):
    log.event("voice.stage.completed", stage="asr", latency_ms=elapsed_ms)
    log.info("Provider ready", provider="asr")
    pool.submit(wrap_context(callback))
# 在 except 中：log.exception("Provider failed", provider="asr")
```

标准 logging.getLogger 的诊断也进入同一根 handler。现有 ROS 代码继续 node.get_logger()，
由收集器归一化。使用现有身份，不生成/回填新的业务 ID；绑定上下文在作用域退出时自动恢复。
线程任务用 wrap_context 捕获提交时上下文；async task 的 ContextVar 自然隔离。
事件名使用稳定的“模块.对象.变化”，不要包含 UUID、用户原话或动态 reason。
字段避免占用 API 的 level/kind/repeat_key 参数名，例如需求等级使用 need_level。

公共故障测试随 `python3 tools/dev.py check` 运行。
`python3 tools/check_logging_runtime.py` 检查原生 ROS once/throttle、源位置、采集循环和正常落盘，
只使用 localhost domain 219；不要与同域测试并行。
本轮验收见 [日志 v2 重构记录](../../validation/logging-v2/README.md)。
