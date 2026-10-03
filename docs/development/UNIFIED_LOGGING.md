# 统一日志：运行、查询与扩展

五模块通过 `packages/observability` 使用同一日志协议。它只依赖 Python 标准库，
不承载事件路由、行为仲裁、动作执行或需求结算。每个模块仍有自己的 pyproject、lock 和环境。

## 日常使用

在主仓根目录执行；本机已准备环境时不需要重新安装模型：

~~~bash
python3 tools/marsdog.py build
python3 tools/marsdog.py up

# 在另一终端查看最近一次 up/smoke
python3 tools/marsdog.py logs --run latest --limit 50
python3 tools/marsdog.py logs --run latest --component action
python3 tools/marsdog.py logs --run latest --level warning
python3 tools/marsdog.py logs --run latest --goal YOUR_GOAL_ID --json
python3 tools/marsdog.py logs --run latest --health
~~~

`latest` 指 `out/local/latest-run.json` 记录的组合运行，可能包含失败运行。
录音试用用结果中返回的具体 `run_directory`：

~~~bash
python3 tools/marsdog.py trial --wav /absolute/path/command.wav --output out/my-trial
python3 tools/marsdog.py logs --run out/my-trial/RUN_DIRECTORY --interaction INTERACTION_ID --utterance UTTERANCE_ID --json
~~~

录音 HTML 报告增加统一日志及写入健康信息，原 ASR/意图/事件/候选/仲裁/动作诊断保持可用。
查询支持 `--event behavior.` 这样的事件名前缀。默认取筛选后最新 100 条；
命令逐行读取，最多扫描两遍，只保留相关身份和最终 N 条记录。坏记录会报告文件和行号，
最多列出 1000 项，不阻止读取其他有效记录；存在坏记录时命令非零退出。

会话查询先匹配 interaction/utterance，再用这些记录中已有的 candidate/behavior/goal ID
查找动作与结果。ID 类型分别匹配；有明确不同会话 ID 的记录不会被混入。
缺少关联 ID 的普通 ROS 文本不能自动归属于某次语音；用模块和时间补充查看。

## 采集路径与兼容

| 来源 | 新结构化输出 | 保留的原输出 |
| --- | --- | --- |
| Voice | Python 日志、VOICE_TRACE、意图线程上下文 | 原文本、VOICE_TRACE 文本格式 |
| Vision | Python 日志、VISION_TRACE；相机和调试入口也接入 | 原文本、VISION_TRACE、原超长记录占位格式 |
| Emotion / Needs | 信号发布、结果处理及各节点运行身份 | 原 ROS 输出；周期状态仍走原话题 |
| Behavior | BT 事件、候选/等待/仲裁/取消/结果决策记录 | BT JSON、显式开启的 decision-trace-v1 |
| Action | 目标、阶段反馈、详细终态、执行回调返回结果 | 原 debug 话题及原 ROS 输出 |
| ROS / C++ | 独立订阅 /rosout，附原 logger、位置和时间 | 原生 ROS 控制台和 ROS 文件 |

收集器不包装 `RcutilsLogger`，因此不改变原调用点和 once/throttle 上下文。
它禁用自己的 rosout 发布以避免反馈循环。启动器给所有进程分配同一 run_id，
每个进程另有随机 instance_id；Emotion 的多个节点不争用同一个文件。

`action.terminal` 是原调试结果发布的观察，`action.callback.result` 是执行回调返回的观察，
后者包含验证失败、执行器忙等未发布 debug result 的路径。两者可能描述同一个目标结果，
不能将日志行数当成动作执行次数。它们都不代替正式 Action Result 或 Needs 结算证据。

`ros.message` 的 component 为 ros，`fields.source_component` 标出已登记的原节点所属模块。
未知或重命名的节点保留源 logger 并标为 external；模块筛选会使用该来源字段。
导航/避障内部代码没有接入改写，已有 /rosout 可作为外部日志读取。

每次运行目录包含：

~~~text
log-manifest.json          # run_id、归属、策略、active/closed
structured/
  voice-<instance>.jsonl   # 每进程独立写入
  voice-<instance>.jsonl.1 # 轮转备份
  voice-<instance>.health.json
  ros-<instance>.jsonl
voice.log / action.log …  # 原 stdout/stderr，兼容诊断
voice-log/ vision-log/ ros-log/
~~~

启动器会把 `MARSDOG_LOG_DIR` 设置为此次 run 的 structured 目录，防止多次运行混写。
单独启动节点时可自己设置它和 run_id；不设置则使用节点原日志目录下的 structured。
单独启动的 ROS 节点需要另起收集器才能归一化原生 ROS 日志：

~~~bash
# 在原有、已 source Humble/本仓安装的启动环境中，为相关进程设置相同值
export MARSDOG_RUN_ID=manual-20261004
export MARSDOG_LOG_DIR=/absolute/path/my-run/structured
python3 -c 'from marsdog_observability.ros import main; main()'
~~~

独立启动不自动生成运行归属清单，因此默认清理工具不会处理该目录。

## 配置与故障行为

环境变量不修改生产 YAML 默认值。五模块结构化级别与本机启动器的原生 ROS 级别可一起调整：

~~~bash
MARSDOG_LOG_LEVEL=DEBUG python3 tools/marsdog.py up
MARSDOG_LOG_DISABLED=1 python3 tools/marsdog.py up
~~~

第二条只禁用结构化写入；原日志与原业务流程仍存在。

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| MARSDOG_LOG_LEVEL | 节点原级别，通常 INFO | DEBUG / INFO / WARN / WARNING / ERROR / FATAL / CRITICAL |
| MARSDOG_RUN_ID | 独立启动生成 UUID；组合启动统一分配 | 本次运行身份 |
| MARSDOG_LOG_DIR | 原日志目录/structured | 单独节点的结构化路径；组合启动自动指定 |
| MARSDOG_LOG_QUEUE_SIZE | 1024 | 普通队列条数，限制 8–8192 |
| MARSDOG_LOG_PRIORITY_QUEUE_SIZE | 128 | 警告、错误、result/terminal/stopped 预留队列，限制 8–1024 |
| MARSDOG_LOG_MAX_BYTES | 20971520 | 单个结构化文件上限，限制 4096–104857600 |
| MARSDOG_LOG_BACKUPS | 4 | 每进程备份数，限制 1–20 |
| MARSDOG_LOG_DISABLED | 未设置 | 1 禁用结构化写入 |

正常与重要日志分别使用有界队列，文件写入由后台线程完成；序列化仍在调用线程进行。
字段深度/集合大小/文本长度受限，单条 JSON 默认最多 16 KiB，超出时用明确占位记录，
并尽量保留截短的身份字段。文件按 UTF-8 字节数轮转，默认每进程最多约 100 MiB。
Voice/Vision/可选 BT 旧文本文件也按 20 MiB + 4 个备份限制；
原 stdout/stderr、ROS 文件及显式旧 decision trace 未改成同一写入器。

队列满直接丢弃并累计 dropped 或 priority_dropped；重要日志也不是绝对不丢。
写入失败累计 sink_errors，退出最多等待 3 秒排空。写入健康每约 5 秒及正常退出更新，
包括 pending、written、oversized、coalesced、writer_alive 和 closed。
降级时 stderr 提示限频为 30 秒。磁盘完全不可写时健康文件也可能无法更新，应同时看 stderr。
`SIGKILL`、断电、卡住的文件系统不保证最后几条落盘；健康状态可能停留在 closed=false。

本机组合的收集器异常会在 result.json 记录 logging_degraded，业务进程继续运行；
原生输出和各模块自己的结构化文件仍可使用。业务进程异常仍按原监督策略处理。
日志不能作为执行成功或“未发生动作”的唯一证据。

字段级脱敏目前覆盖 password、authorization、api_key、access_token、refresh_token。
任意消息文本和语音识别内容不会自动识别并脱敏；分享日志前应按实际内容筛选。

## 存储清理

轮转限制单进程日志；跨运行保留通过显式清理命令完成：

~~~bash
# 只显示计划，不删除
python3 tools/marsdog.py logs --prune --keep-runs 20 --max-total-mb 1024

# 审阅计划后执行；可用 --root 指定某个 trial 的输出根目录
python3 tools/marsdog.py logs --prune --keep-runs 20 --max-total-mb 1024 --apply
~~~

只清理带有效 log-manifest 的已关闭运行，保留最近运行优先；总预算仅计算受管日志。
运行中的日志计入预算但不删除，单独报告 active_budget_exceeded。
仅删除固定日志目录/运行根目录的日志文件，不递归删除运行目录。
WAV、模型、配置、SQLite、result.json、HTML 报告和历史未登记目录都保留；
备份或分享完整试用证据后再清理。进程崩溃留下的 active 清单不会自动判定为可删除。
这是按需清理，没有新增定时任务。

## 扩展方式

新模块只依赖公共包入口，保持原业务通信边界。已有五模块依赖固定版本 0.1.0，
uv 从本仓 packages/observability 安装；模块环境独立，未统一到根环境。
离线交付 wheel 时同时交付该公共 wheel。colcon 构建使用同一源码，
ROS 包名 marsdog_observability；默认构建从 15 包增加到 16 包。

~~~python
from marsdog_observability import configure, emit, bind_context, wrap_context

configure("voice")  # 实际进程入口调用；纯逻辑模块 import 不创建文件/线程
with bind_context(interaction_id=current_session, utterance_id=current_utterance):
    emit("voice.my_stage", {"status": "started"})
    pool.submit(wrap_context(callback))
~~~

使用现有业务 ID，日志不得生成并回填业务目标或改变事件授权。
反复等待理由可传 repeat_key；内容变化后仍记录。高频帧/波形/状态全文不应逐条放 INFO。
原生 ROS 调用继续用 node.get_logger()。标准 Python 异常日志继续使用 exc_info=True。
新结构化事件名采用“模块.阶段”，与 EVT_* 业务事件和 ACT_* 动作 ID 区分。

协议见 [envelope v1](../../interfaces/observability/README.md)。
公共故障测试随 dev.py check 运行；安装后原生 ROS 过滤测试为：

~~~bash
python3 tools/check_logging_runtime.py
~~~

它只用 localhost domain 219，不连接设备；记录一次普通 INFO/WARN、多次 once/throttle 调用，
验证原输出数量、源位置、无采集循环及退出落盘。不要与同 domain 的其他测试并行。
验收结果见 [本次重构记录](../../validation/unified-logging/README.md)。
