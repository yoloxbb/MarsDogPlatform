# Visual event v1 兼容契约

端点 /perception/visual_event，ROS 类型 std_msgs/msg/String，Vision 发布、
BT/Emotion/Action 消费；可靠性沿用 BEST_EFFORT，具体配置见原节点。
JSON schema_version 是整数 1。生产规范化仍在
modules/vision/marsdog_vision_interaction/messages/visual_event.py。

| 字段组 | 原有含义 |
| --- | --- |
| header.stamp / frame_id | 感知时间及坐标系；不替换为接收时间 |
| vision_epoch / snapshot_id / sequence | 生产实例与快照标识；重启后不能混用旧目标 |
| active_target / human_candidates | 目标引用、身份、跟踪状态、朝向和距离证据 |
| humans / tracked_objects | 人体和物体观测；不表示行为执行许可 |
| events | 字符串事件序列，保留来源顺序 |
| last_seen_age_ms / tracking_state | 观测新鲜度与跟踪状态；身份不充当 target_id |
| range_valid / distance_m / pose_3d | 原有距离有效性、深度和坐标；未知不能伪装为 0 距离 |

BT 严格要求整数版本和字符串事件数组，再更新原场景缓存。
直接事件 STRANGER/FALL/STOP_GESTURE 沿用出现边沿去重，缓存超时后重新判边；
目标有效性和服务降级仍由原规则决定。消费者回调在缓存锁外调用。
缺少 human_candidates 时只在 epoch 和有效 track_id 存在时构造兼容目标。

Emotion 按已有感知适配器选择事件并更新领域状态，不复用 BT 执行权限逻辑。
Action 的 JSON 分发对损坏或非 object 消息向运动相关适配器传空快照，保留失效停止路径；
不会把“解析失败直接返回”推广为所有消费者的共同策略。

本轮刻意保留已有差异：例如 humans=null 等部分结构错误可能在 BT 更新部分接收信息后
抛错；兼容基线记录该异常，不把它伪装成成功或顺便改变其行为。负例不构成推荐生产格式。

`python3 -B tools/check_visual_contracts.py` 验证 7 组真实 Vision 规范化输出及
33 个序列场景：身份/目标、空帧、边沿重复/消失/重现、超时、错误版本/类型、
坏 JSON 和多个消费者的不同容错。基线在 66c7eaa 修改前采集。
固定时钟与随机种子，候选仅去除随机 candidate_id/created_at；保留内容、顺序、
缓存、状态、副作用和异常。无 DDS/模型/相机；DDS 由单独的本机 smoke 验证。
