# 五模块统一日志验收

2026-10-04，基于 `9ac868d` 在 `refactor/unified-logging` 完成。
操作与扩展见 [统一日志](../../docs/development/UNIFIED_LOGGING.md)，
机器可读证据及报告哈希见 [summary.json](summary.json)。
原始运行输出留在被 Git 忽略的 out/unified-logging，未清理既有录音或运行数据。

## 实现与兼容边界

- 新增无第三方运行依赖的 marsdog-observability 0.1.0；独立 wheel / ROS 安装使用同一源码。
- 五模块统一 JSONL envelope、run/process 身份、有界双队列、UTF-8 轮转、退出排空和健康计数。
- Voice/Vision 旧 TRACE、BT JSON、decision-trace-v1、正式 ROS IDL/话题/任务协议均保留。
- 原生 ROS 日志由独立 /rosout 观察者归一化，原调用点的 severity/once/throttle 保留。
- 查询按已有 interaction/utterance/goal 等身份关联；收集器崩溃不停止业务进程。
- 录音诊断报告增加关联日志与健康数据；受管已关闭运行提供只读保留计划及显式清理入口。
- 包清单只增加公共日志 exec_depend。历史门禁先移除唯一这条字面增量，
  再与原冻结字节/原 Action XML 比较；没有刷新任何冻结契约基线。
- 五个锁文件只新增本地公共包，原第三方版本全部不变。
  Voice/Behavior 由离线 uv lock 添加；其余使用等价增量记录避免不可用的平台元数据重解析，
  所有锁均通过 uv lock --check --offline 和 --locked 安装。
- 导航/避障内部、生产默认配置、算法模型、动作门限、取消及需求结算语义未调整。
  可选 Nav2 装配器仅将“按列表位置移除 inputs”改为“按进程名移除”，以容纳新增收集器。

## 软件验证

| 项目 | 结果 |
| --- | --- |
| 架构与接口检查 | 16 个 ROS 包，21 个既有接口，通过 |
| 平台工具测试 | 115 通过 |
| 公共日志测试 | 10 通过；线程/async 上下文、队列满、写入失败、轮转、超长 UTF-8、异常、禁用 |
| Voice Humble 全量 | 430 通过 |
| Vision 全量 | 297 通过，3 个原硬件测试跳过 |
| Emotion | 374 entries 通过，含 218 tests 与 156 subtests |
| Behavior | 538 通过 |
| Action 纯环境全量 | 429 通过，29 个明确 ROS/GUI 跳过 |
| 五模块独立 wheel | 全部通过；公共包四个模块也验证安装来源与源码哈希 |
| Audio / Visual / State | 46 / 33 / 34 个冻结场景一致 |
| VoiceTask / VisionTask | 每侧 18 个场景一致 |
| 原结果契约与受保护文件 | 25 通过 |
| Action Humble 回调 | 35 通过，未跳过 |
| Action DDS transport | 通过；取消后保持 ownership 直到终态 |
| Action shutdown | SIGINT、SIGTERM 两项通过 |
| ROS build / doctor / smoke | 通过；新增收集器正常关闭，无强制退出 |
| 进程生命周期 | 正常中断、Action 崩溃、收集器崩溃三项通过；无遗留进程 |
| 决策 DDS 场景 | 5 项通过 |
| 感知恢复 DDS 场景 | 7 项通过 |
| 原 CPU Voice→BT→Action 流程 | flow 验收通过，不宣称模型质量达标 |
| 独立日志 DDS | 原 INFO/WARN 数量、once/throttle、源位置、无循环、退出落盘均通过 |
| 查询/清理 | CLI 实际查询通过；仅执行既有运行清理 dry-run；删除测试限临时目录 |

这些计数存在不同层级和重复覆盖，不应加总为独立用例数。
ROS 测试全部在 localhost 隔离 domain，设备 I/O 明确模拟。

## 真实 CPU 录音链路与日志

使用之前已有的 Microsoft Huihui Desktop 合成 WAV，不是用户真实录音；
运行真实 CPU ASR 和既有业务链路。

| 输入 | 原业务终态 | 统一日志验收 |
| --- | --- | --- |
| 回家 | go_home SUCCESS / completed | 796 条记录，29 条会话关联记录 |
| 坐下 | sit_down FAILURE，lite3_action_gated: ACT_BASIC_SIT proxy / unverified | 774 条记录，26 条会话关联记录 |

每次运行均包含 Voice、Vision、Emotion、Behavior、Action 及 ROS 观察者记录，
同一 run_id，9 个不同进程实例；所有 writer 正常关闭。
两次运行的 dropped、priority_dropped、sink_errors、pending 全部为 0。
关联记录包含语音完成、收到声音事件、候选选择、Goal 分发、Action 回调结果和 BT 终态。
Vision/Emotion 运行日志保留在同一 run；这些命令没有关联到它们的业务 ID 时，
查询不会凭时间或名称伪造一条链。

坐下失败是原安全门限的预期观察，未将 Goal 接受或代理动作伪报为成功；
回家完成也未新增电量/充电结算。

## 已知限制

没有实机、开发板、NPU 或模型精度优化验收。
公共写入故障和丢弃会降级诊断，但不会变成动作授权或成功证据。
急停进程、断电、队列过载或卡住的磁盘仍可能丢日志；
重要日志预留队列同样有界。旧 stdout/stderr/ROS/decision trace 的总量由显式运行清理管理，
不是所有历史输出都已替换为同一种写入器。详见操作文档的故障与存储章节。
