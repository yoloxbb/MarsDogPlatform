# 五模块应用协议目录

此目录统一查阅入口、字段语义和兼容样例；ROS 类型/端点权威仍为
[registry.json](../registry.json) 与各自 IDL。不同领域保留自己的解析和容错策略，
不新增运行时总线或跨模块业务 common。

| 协议 | 生产与消费 | 兼容门禁 |
| --- | --- | --- |
| [audio v2](audio-event-v2/README.md) | Voice → BT / Emotion | check_audio_contracts.py，46 场景 |
| [visual v1](visual-event-v1/README.md) | Vision → BT / Emotion / Action | check_visual_contracts.py，33 场景 |
| [state v2](state-v2/README.md) | Emotion / Needs → BT | check_state_contracts.py，34 场景 |
| [任务服务](perception-task/README.md) | BT / Action → Voice / Vision | check_task_contracts.py，每端 18 场景 |
| [ExecuteBehavior](execute-behavior/README.md) | BT ↔ Action → Needs 结算 | 25 结果契约、35 ROS 回调、DDS 取消终态 |

从主仓根运行 `python3 -B tools/<门禁文件>`。前三种 JSON schema_version
分别是整数 2、整数 1、字符串 "2.0"，不得以统一版本字段为由改写线上消息。
VoiceTask/VisionTask 字段相同但 ROS 类型不同；既有 waypoint 对 VoiceTask 的依赖保留。

cases.json 记录固定输入及负例；baseline.json 是重构前真实实现的输出。
正常测试只读基线，输出 actual.json/result.json，差异必须失败，不得自动更新基线。
每个生产/消费阶段用所属模块的 .venv 和独立进程；工具不 import 其他领域业务。
动态 ID/时钟采用文档化的确定性替身，测试不会加载模型或控制硬件。

新功能应在所属模块修改实现，并同时审查生产、消费、取消和结算。
刻意改变容错或产品语义需要单独决策，不能夹带在目录整理中。

排障使用 [统一日志 v2](../observability/README.md) 的 behavior.* 观察；它不是线上 ROS 协议，不改变上述身份和版本。

事件、意图、行为、动作及端点的命名和跨配置引用门禁见 [标识规范及目录](../naming/README.md)。
