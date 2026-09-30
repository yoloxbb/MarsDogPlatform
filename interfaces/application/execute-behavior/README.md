# ExecuteBehavior 与结果结算

公开类型 marsdog_interfaces/action/ExecuteBehavior，端点 /execute_behavior。
权威字段见 [公开 IDL](../../ros2/marsdog_interfaces/action/ExecuteBehavior.action)；
历史 Action 包 IDL 与兼容导入仍保留。本轮不更改字段、状态或超时约定。

Goal 保留 goal_id、behavior_id、behavior_name、priority_level、params_json、
timeout_sec。params_json 的 object 校验发生在接受前，异常 accepted 回调仍走原保护。
Feedback 保留进度、safe_to_interrupt 和当前动作；Result 保留终态、
reason/reward、emotion_delta_json、need_delta_json、metadata_json。

取消 ACK 只是取消请求被接受；目标归属必须保留到终态 Result 后才能清理。
抢占、长动作预约、lease、急停、导航取消真值与超时计算保持原顺序。
这些协调从节点移入 Action 自己的 goal_lifecycle/goal_execution，
构造 ROS 消息与枚举仍由节点注入；不修改导航适配器内部算法。

Action → BT → Needs 仍通过既有结果和证据结算：不能把取消、失败或无有效证据的
成功当成可结算结果；GO_HOME 继续不结算 Energy，不伪造 BMS 电量。

| 验证 | 范围 |
| --- | --- |
| tools/check_contracts.py | 25 项独立进程结果/证据契约，真实 Action/BT/Needs |
| tools/check_action_callbacks.py | 35 项真实 ROS 回调测试，Humble 类型 + 替身协作者，无跳过 |
| tools/check_action_transport.py | 当前安装的 BT adapter + 测试 Action server，真实 DDS，ACK 后保留归属直至 Result |
| tools/check_action_shutdown.py | 当前安装的 Action，SIGINT/SIGTERM 停止后退出，模拟 Lite3 I/O |
| tools/marsdog.py smoke | 默认隔离组合的安装节点、感知/状态/任务/动作链路 |

回调和 DDS 门禁互补，不把测试 server 称为真实运动执行器，也不把替身 I/O
称为硬件验收。工具复用历史测试探针，不重新执行迁移。
