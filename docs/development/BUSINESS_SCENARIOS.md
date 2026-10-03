# 五模块业务场景验收

五模块兼容性重构已在 R1–R4 完成。本页把已有回归与新增的进程恢复场景关联起来，
避免把重复测试当作新功能，也避免把 mock 输入通过记成相机、模型或实机验收。
重构基线为 6d75931；原测试和冻结契约不刷新。

## 验收矩阵

| 业务场景 | 可复现入口 / 原有断言位置 | 验收边界 |
| --- | --- | --- |
| 唤醒选人、方位优先、目标锁定 | BT tests/test_voice_engagement.py；marsdog_behavior/tests/test_perception_cache.py；dev.py test behavior | 不使用熟人身份替代目标引用；陈旧/不稳定/超角度目标不选；纯逻辑 |
| 连续会话、hold/renew/release、旧会话隔离 | Voice tests/test_session_recovery.py；dev.py test voice --ros；下方新场景 1–4 | 新场景使用真实 Voice 服务、DDS 和安装后的 BT 感知适配器；输入为 mock |
| 视觉中断、超时、迟到回复、重启后 epoch | 下方新场景 5–7；check_visual_contracts.py | 进程暂停/恢复/重启；不声称测试了真实相机断流 |
| 相机陈旧不刷新目标 | Vision tests/test_runtime_safety.py 的 test_stale_camera_does_not_refresh_cached_target；dev.py test vision | 原逻辑回归，真实相机仍待接入 |
| 目标丢失时停止、重新捕获不换成干扰人、取消 | Action tests/test_visual_target_approach_adapter.py；dev.py test action | 模拟适配器输入，保持原运动门限 |
| 取消抢占、旧 Goal 锁归属、ACK 与终态 | BT marsdog_behavior/tests/test_runtime_architecture.py；check_action_transport.py；check_action_callbacks.py | 纯逻辑、真实 DDS transport、真实 ROS 回调分别记账；transport 的 Action 服务端为测试替身 |
| 需求结算、重复/迟到结果、Energy 证据 | check_contracts.py；BT tests/test_recharge_result_lifecycle.py | Action→BT→Needs 25 个固定契约；go_home 不产生需求结算；模拟电量不成为真实充电证据 |
| 五模块启动与回家链路 | marsdog.py doctor；marsdog.py smoke | 全部安装后的节点，Voice→BT→Action→航点→模拟 Nav2；检查 GO_HOME 终态及硬件话题无发布者 |
| 退出和异常传播 | check_action_shutdown.py；check_local_lifecycle.py | Action SIGINT/SIGTERM 停止再退出；supervisor 子进程崩溃必须整组 FAIL 并清理 |
| 原有导航故障恢复 | check_nav2_recovery.py；validation/real-nav2 | 历史真实 Nav2 + 模拟地图/里程计；本轮不重写导航、不重新宣称实机通过 |

路径分别相对于所属 modules/<模块>。各模块单测总数、跳过原因、独立 wheel 验证
见 [R2–R4 冻结证据](../../validation/compat-refactor/r2-r4/README.md)。
声/视觉/状态契约使用真实生产与消费逻辑，但本身不运行 DDS；
它们与进程验收互补，数量不可当作不重叠业务用例简单求和。

## 新增的感知进程恢复门禁

已有 Humble、各模块环境和当前源码的 ROS 安装后，在主仓根目录执行：

~~~bash
python3 -B tools/dev.py check
python3 -B tools/marsdog.py build
python3 -B tools/check_business_scenarios.py
~~~

若已构建相同源码，不必重建；工具校验 build receipt 与源码指纹，不接受陈旧安装。
结果在 out/business-scenarios/<UTC>/result.json，同时保留 observation.json、服务调用、
生成配置及哈希、节点日志、Python/安装来源、每代进程 PID/退出码。
顶层 result.json 指向最近一次结果；启动先写 RUNNING，异常或不完整报告写 FAIL。

| 编号 / case id | 注入 | 必须观察到 |
| --- | --- | --- |
| 1 voice-held-continuous-session | 空闲阈值 3 秒，hold 超过阈值，再续租同 token | 会话 ID 不变，hold 有效，续租返回 renewed |
| 2 voice-stop-stale-requests | 停止并开新会话，同 token，提交旧会话的 start/hold/release | BT 收到 idle；旧请求拒绝且不破坏新 hold；正确 release 幂等 |
| 3 voice-lease-expiry | 短租约到期，再等待空闲阈值 | hold 清除，会话回到 idle |
| 4 voice-restart-rediscovery | 持有 hold 时正常停止并重启 Voice，保留原 client | 服务重新发现；新实例空闲且无旧 hold；新会话拒绝旧请求 |
| 5 vision-timeout-stale-cache | SIGSTOP 自己启动的 Vision，等待缓存及查询期限 | BT 缓存无人；请求回调一次且为 None |
| 6 vision-resume-late-response | SIGCONT 原 Vision 后再次查询 | 新查询恢复；旧请求迟到回复不能再完成旧决策 |
| 7 vision-restart-new-epoch | 正常停止并重启 Vision，保留原 client | 新 epoch；旧 target_id 不在新结果中；BT 选中当前 epoch |

Voice/Vision 使用已安装的 mock 节点，BT 使用已安装的真实 PerceptionClientAdapter。
本门禁没有启动完整 BT 仲裁器、Action 或 Needs；完整链路由上表 smoke、取消及结果
门禁承担。mock Vision 会持续生成目标，所以本门禁暂停的是视觉进程，不以相机断流
描述它。恢复策略属于测试编排，没有给生产 supervisor 添加自动重启策略。

运行使用 localhost ROS domain 216 及文件锁；同一主机的不同克隆不要同时运行此门禁。
只对自己创建的进程发信号；守护进程在观察者失败后也清理同组后代。
PASS 要求七项完整、四代节点均正常退出并回收、无强杀、安装来源正确且没有硬件话题
发布者。平台测试另验证不完整/错误报告不能通过，以及观察者退出后暂停的子进程可清理。
Python 优化模式会禁用断言，门禁显式拒绝该模式。

已接入 .github/workflows/platform.yml 的手动 Humble job。
没有配置远端 runner，配置存在不等于 hosted CI 已运行。

## 完整 BT / Action 仲裁与录音试用（P0–P2）

新增 `check_decision_scenarios.py` 在 localhost domain 217 运行安装后的完整 BT 和
Action，覆盖重复事件、同级命令排队、STOP 抢占、陈旧目标拒绝及 Needs 优先于 Emotion。
协议输入为明确样例，设备/导航模拟；要求每个 Goal 恰好一个终态，组件正常回收。
该门禁补充上面的感知进程恢复七场景，详情见 [功能流程](FEATURE_WORKFLOW.md)。

`marsdog.py trial --wav /absolute/path.wav` 接入任意合规的预切分 WAV，
用真实 CPU ASR，经安装后的 Voice → DDS → BT → Action 生成关联诊断。
见 [录音试用](RECORDING_TRIAL.md)；合成录音试验、原固定 CPU flow、协议样例仲裁
和实机验收分别记录，不能相互替代。

## 修改后的最小回归

会话或视觉缓存改动：受影响模块单测 + 对应 audio/visual/task 契约 + 本恢复门禁。
抢占/动作改动：BT/Action 单测 + 取消 transport/callback/shutdown。
结算改动：Emotion/BT/Action 对应单测 + check_contracts.py。
启动或交付改动：平台检查 + 干净环境 build/doctor/smoke。
冻结 baseline.json 只读；失败时修实现或提交明确的兼容性决策，不自动重采样消除差异。
