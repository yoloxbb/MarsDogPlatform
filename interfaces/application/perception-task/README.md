# VoiceTask / VisionTask 应用约定

| 端点 | ROS 类型 | IDL |
| --- | --- | --- |
| /perception/voice/task | marsdog_voice_interaction/srv/VoiceTask | modules/voice/srv/VoiceTask.srv |
| /perception/vision/task | marsdog_vision_interaction/srv/VisionTask | modules/vision/srv/VisionTask.srv |

请求字段 task_id、task_type、params_json；应答 success、task_id、task_type、
result_json、error_message、latency_ms。相同字段不代表可替换 ROS 类型。
waypoint 的历史类型依赖保持原状，导航内部由其负责人调整。

保持旧 envelope 规则：空参数字符串解析成 {}；对象直接传入；兼容 key/value 数组，
重复 key 后者覆盖，非字典项忽略；其他合法 JSON 值按 {} 处理。
解析异常或任务异常返回失败与错误文本；结果的 ok 缺省为 True，按原 bool 转换，
没有引入新的严格类型校验。领域任务名、声纹/会话、目标查询仍在各自 task_router。

协议看似相同仍保留两个领域 codec：Voice 完成 trace 带 interaction_id 和任务结果；
Vision 有 stage_start/stage_complete trace。延迟日志分别沿用两位和三位小数，
应答 latency_ms 的原计算保留。共用严格错误转换器会改变现有行为。

Vision 的 `locate_person_once` 接受 `target_id`，成功结果为
`{ok:true,target_id,target}`；`target` 是仍处于 tracking 的视觉候选。目标缺失、过期或
不再 tracking 时返回 `person_target_not_found`。该任务不调用 SLAM，也不返回地图坐标、
深度质量或导航目标。该语义变更来自上游 `1904258`；VisionTask ROS 类型和 envelope 不变。

`python3 -B tools/check_task_contracts.py` 在系统 Humble 可导入时，
分别用 Voice/Vision 自己的 Python 调用真实服务回调，每端 18 个固定场景，
合计 36 份观测。覆盖参数类型、数组键、JSON 错误、ok 缺失/真假/字符串、
非 object 结果与任务异常，比较应答、任务入参和 trace 顺序。
任务执行端口及 perf_counter 用确定性替身；不实例化节点、加载模型或连接设备。
实际任务路由、会话、取消和 provider 协作由原模块全量单测覆盖；
服务 DDS 与安装节点另由默认组合 smoke 验证。
