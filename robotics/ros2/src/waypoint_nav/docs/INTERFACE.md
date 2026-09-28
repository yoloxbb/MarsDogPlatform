# Platform amendment: explicit operator recovery release

This amendment supersedes any legacy instruction below that uses ordinary
`cancel` to release a recovery lock. Approved on 2026-09-28.

- `cancel` in RECOVERY_REQUIRED records cancellation intent and retains the lock;
  only a confirmed Nav2 terminal result can resolve it automatically.
- Explicit operator operation: task_type=`release_recovery`, with params_json
  containing protocol_version="1.0", client_id="marsdog_action_executor",
  target_task_id, and operator_confirmed_stopped=true (a JSON boolean).
- The operator must first verify that the robot is stopped. This field is an
  attestation, not authentication or a physical stop detector. Automated clients
  must never generate this operation. Existing transport has no operator auth.
- Missing/false/non-boolean confirmation: OPERATOR_CONFIRMATION_REQUIRED.
  Non-recovery active task: NOT_IN_RECOVERY. Existing ownership/active/terminal
  checks still apply. Success emits INTERRUPTED/RECOVERY_RELEASED, never success
  or Nav2-confirmed cancellation. Status is persisted before the lock is released.
- Deploy the updated Action parser with this server. Historical Action versions
  reject RECOVERY_RELEASED. ROS service type and endpoint remain unchanged.

---

# waypoint_nav 点位导航接口（协议 v1）

本包接收已解析的点位 ID、精确地点名称或保留目标 `11`，取得 Pose 后向 Nav2
`/navigate_to_pose` 发送目标。普通点位的 Pose 来自 `waypoints.yaml`，`11` 的 Pose
从实时 `/map` 随机生成。语音、睡觉、吃饭等意图与到点后的行为 Stage
由 Tree 和 MarsDogAction 处理。生产环境只有 MarsDogAction 调用本包。

> 代码采用 v1 状态机和 SQLite 持久化。板端 Nav2 的重启恢复与实际移动
> 仍需按本文末尾的场景完成集成测试，测试前不要把重启恢复视为已验证。

## 接口

| 用途 | 名称 | 类型 |
|---|---|---|
| 导航、取消、查询 | `/waypoint_nav/task` | `marsdog_voice_interaction/srv/VoiceTask` |
| 状态 | `/waypoint_nav/status` | `std_msgs/msg/String`，JSON |
| 已校验点位标记 | `/waypoint_nav/markers` | `visualization_msgs/msg/MarkerArray` |

继续复用板端已有的 `VoiceTask`，不新增接口包。Service 字段为：

```text
string task_id
string task_type
string params_json
---
bool success
string task_id
string task_type
string result_json
string error_message
float64 latency_ms
```

`task_id` 长度为 1～128，只允许字母、数字、`.`、`_`、`:`、`-`。
所有请求的 `params_json` 都必须是 JSON object，包含
`"protocol_version":"1.0"` 和
`"client_id":"marsdog_action_executor"`。Service 响应原样回显请求的
`task_id`、`task_type`；`latency_ms` 只统计 Service 处理耗时。

调用方和导航栈必须使用一致的 `RMW_IMPLEMENTATION`；联调时核对实际进程。

## goto_place

请求示例（下方是解码后的 `params_json`）：

```text
task_id: action:goal-001:waypoint
task_type: goto_place
```

```json
{
  "protocol_version": "1.0",
  "client_id": "marsdog_action_executor",
  "place": "客厅",
  "timeout_sec": 120.0,
  "preempt": false,
  "terminal_retention_sec": 86400
}
```

网页固定显示 `A`–`J` 十张地点卡片。地图没有可加载地点文件时，`A`–`E` 默认名称
依次是客厅、厨房、卧室、卫生间、充电桩，`F`–`J` 为「地点 F」到「地点 J」。
加载已有地点文件时，已标记卡片显示文件中的名称，其余空卡片统一显示「地点 A」到
「地点 J」，不补预设名称。无需点击按钮添加卡片。
名称可以编辑，示例名称不代表睡觉、吃饭等行为用途。
保存时只写入实际标记的点位，未标记的卡片不进入地点文件；
因此文件可以只包含 1、2、3 个点位或为空。删除地点不会重排已有 ID，
ID 随点位持久化，不按 YAML 条目顺序重新编号。

`place` 可以是地点文件中的 waypoint ID（如 `A`），也可以是
精确地点名称（如 `客厅`，改名后可为用户自定义的文字）。只去除首尾空白，不做模糊匹配或意图解析；
地点名称在文件中必须唯一。若名称与另一点位的 ID 相同，ID 优先。
名称可在网页中编辑，改名后调用方也要更新。
普通点位的 `matched_id` 返回匹配到的稳定 waypoint ID；随机目标的返回值见下文。
`timeout_sec` 是从任务
`QUEUED` 落盘起算的点位导航预算，不包含后续 Stage。v1 不允许
`preempt=true`。`terminal_retention_sec` 是调用方要求的最短保留时间，
不能小于 86400；服务端配置若不能满足则拒绝受理。
本节示例里的 `客厅` 对应 `A` 仅为示例，实际对应关系以当前地点文件为准。

### 随机导航目标 `11` / `K`

`"11"` 和 `"K"` 是同一个随机导航目标的两个入口，均为保留 ID，
不能用作普通地点文件的 ID。它不是网页的第十一张卡片，也不写入
`waypoints.yaml`。Tree 仲裁后仍由 MarsDogAction 通过同一个
`goto_place` 请求提交 `params_json.place="11"` 或 `"K"`（均为 JSON 字符串，
不能写数字 11；`K` 区分大小写）。两个入口都归一为
`matched_id="11"`、`place="随机点位"`，状态与查询也使用这组返回值；
Tree 不应在 A–J 地点清单里查找 `11` 或 `K`。

```text
task_id: action:goal-002:waypoint
task_type: goto_place
```

```json
{
  "protocol_version": "1.0",
  "client_id": "marsdog_action_executor",
  "place": "11",
  "timeout_sec": 120.0,
  "preempt": false,
  "terminal_retention_sec": 86400
}
```

导航端每次收到新的随机导航任务，先用当前 `/map` 中**非未知栅格**
求出有效地图的最小外接矩形，再在这个有效区域的中央取宽、高各一半的
矩形；不按整张地图画布的宽高计算。落点始终必须是占用值为 `0` 的
已知空闲栅格，未知区和障碍格不能作为目标。

选点顺序为：中央且周围有安全间距 → 中央的任意已知空闲格 →
整个有效区域内有安全间距的格 → 整个有效区域内任意已知空闲格。
安全间距默认是以目标为中心、各方向 `0.35` 米的方形邻域，可通过
启动参数 `random_clearance_m` 调整。因而只要已收到有效地图且其中
至少有一个空闲格，就不会因为中央区域为空或间距不足而拒绝随机任务。
目标位姿在受理时写入
任务存储；同一 `task_id` 重发不会重新抽点，也不会发起第二次导航。
随机目标朝向固定为地图坐标系的零度。若没有 `/map`，返回
`RANDOM_MAP_UNAVAILABLE`；地图无效或完全没有已知空闲格时返回
`RANDOM_TARGET_UNAVAILABLE`。这两种情况无法生成真实导航目标，
Service 不创建任务。普通点位文件缺失或与地图不匹配
不影响 `11` 使用当前 `/map` 选点。
最后一级回退可能选中靠近障碍的空闲格；Nav2 的代价地图和规划结果仍须
决定能否到达，实际导航成功以 Nav2 终态为准。

以地点名称提交时，响应和状态中的 `matched_id` 与请求中的 `place`
本来就不同。调用方应先按 `task_id` 关联可能早于 Service 响应到达的
状态，再用响应中的 `matched_id` 核对缓存状态；漏掉响应时可用 `query`
恢复。不能把 `matched_id` 与原始中文 `place` 直接比较。

受理响应的 `success=true`，`result_json` 示例：

```json
{
  "accepted": true,
  "matched_id": "A",
  "place": "客厅",
  "message": "accepted"
}
```

这只表示任务已持久化为 `RUNNING/QUEUED` 并进入处理流程，不表示
Nav2 已接受目标或机器人已到达。当前有未决任务时返回
`success=false`、`code=BUSY`，不会抢占或取消旧任务。重复
导航 `task_id` 返回 `DUPLICATE_TASK_ID`；终态详情过期后返回
`TASK_ID_RETIRED`。两种情况都不会启动第二次导航。

服务端只在地点文件通过当前 `/map` 的分辨率、原点与尺寸校验，且 Nav2
Action 服务可用时受理新任务。此校验不保证目标可达或行为 Stage
有足够动作空间。

## 状态与查询

每条状态是同一任务的持久化快照，先提交 SQLite 事务，再发布 Topic。
`sequence` 从 1 开始，单任务每次状态变化递增；同一任务的
`matched_id` 和 `place` 不变。Topic 不重放，订阅方漏掉消息时使用
`query` 读取存储中的同一份快照。

```json
{
  "task_id": "action:goal-001:waypoint",
  "task_type": "goto_place",
  "state": "RUNNING",
  "code": "NAV2_ACCEPTED",
  "matched_id": "A",
  "place": "客厅",
  "message": "Nav2 已接受导航目标",
  "safe_to_interrupt": true,
  "sequence": 3
}
```

| state | code | 终态 | 含义 |
|---|---|---:|---|
| `RUNNING` | `QUEUED` | 否 | 已落盘，确认尚未向 Nav2 发送 |
| `RUNNING` | `DISPATCHED` | 否 | UUID 和发送意图已落盘，Nav2 是否收到未知 |
| `RUNNING` | `NAV2_ACCEPTED` | 否 | Nav2 已接受 |
| `RUNNING` | `RECOVERY_REQUIRED` | 否 | 无法确认 Nav2 状态，新导航被阻止 |
| `SUCCEEDED` | `NAV2_SUCCEEDED` | 是 | Nav2 确认到达 |
| `FAILED` | `GOAL_REJECTED` | 是 | Nav2 拒绝目标 |
| `FAILED` | `INTERNAL_ERROR` | 是 | 已确认没有发送 Goal 的内部失败 |
| `FAILED` | `TIMEOUT` | 是 | 未下发前超时，或 Nav2 确认停止后的超时 |
| `FAILED` | `NAV2_FAILED` | 是 | Nav2 返回失败终态 |
| `INTERRUPTED` | `CLIENT_CANCELLED` | 是 | 目标化取消已确认，或 QUEUED 原子撤回 |
| `INTERRUPTED` | `NAV2_CANCELED` | 是 | Nav2 确认取消，原因不是本次客户端取消 |

`QUEUED` 仅在能够原子撤回时 `safe_to_interrupt=true`；
`DISPATCHED`、`RECOVERY_REQUIRED` 和全部终态均为 `false`。
`NAV2_ACCEPTED` 只在能安全定向取消且尚未请求取消时为 `true`。
Tree 通过 MarsDogAction 的 Feedback 判断是否可发起抢占；替代
Goal 必须等旧任务真实终态和 Action 执行锁释放，才能开始导航。

查询请求使用新的请求 `task_id`，`task_type=query`，`params_json` 中
除通用字段外再带 `target_task_id`。查询成功时 `success=true`；
即使目标不存在，查询操作本身也返回 `success=true`：

```json
{
  "found": true,
  "target_task_id": "action:goal-001:waypoint",
  "status": {"task_id": "action:goal-001:waypoint", "...": "与状态 Topic 相同"}
}
```

完整终态默认保留至少 24 小时。详情过期后保留不自动清理的
task ID tombstone；查询返回 `found=false, expired=true,
code=TASK_ID_RETIRED`。从未存在的 ID 返回 `found=false,
expired=false`。

## cancel

取消请求使用独立请求 `task_id`，`task_type=cancel`，并在
`params_json` 中带通用字段及 `target_task_id`。只能影响完全匹配的
活动任务。目标不存在、不属于该客户端、已经终态或不是当前活动任务时，
Service 返回 `success=false`，不会触碰其他任务。

成功响应 `success=true`，`result_json` 含
`accepted=true`、`target_task_id`。这只是受理取消，不是已停止。

- `QUEUED`：若尚未发送，原子撤回并发布 `INTERRUPTED/CLIENT_CANCELLED`。
- `DISPATCHED`：记录取消意图，等待 Nav2 接受结果，不能立即发布终态。
- `NAV2_ACCEPTED`：按 UUID 定向取消，等待 Nav2 Action 真实结果。
- 若 Nav2 成功先发生，最终仍为 `SUCCEEDED/NAV2_SUCCEEDED`。

服务端从受理取消起等待最多 **5 秒**确认；无法确认时进入非终态
`RUNNING/RECOVERY_REQUIRED`，节点进入 `RECOVERY_BLOCKED` 并拒绝
新导航。MarsDogAction 的替代 Goal 执行锁等待预算为 **8 秒**。
取消受理响应和 Nav2 的 CancelGoal 受理响应都不能充当终态。

## 持久化与重启

SQLite/WAL 文件默认位于 `~/.ros/waypoint_nav.sqlite3`。创建任务、
状态变化、取消意图均先落盘。`DISPATCHED` 保存事先生成的 Nav2
goal UUID 和发送意图，然后调用 `ActionClient.send_goal_async`。
节点重启后：

- `QUEUED` 可证明未发送，记录为 `FAILED/INTERNAL_ERROR`；
- 其余未决任务进入 `RUNNING/RECOVERY_REQUIRED` 和节点级
  `RECOVERY_BLOCKED`；
- 服务端用保存的 UUID 调用 Nav2 的 GetResult 和定向 CancelGoal；
- 只有得到真实 `SUCCEEDED`、`CANCELED` 或 `ABORTED` 结果，才写入终态；
- `STATUS_UNKNOWN` 不能证明目标已停止，保持阻塞，新导航被拒绝。

遇到长期 `RECOVERY_BLOCKED`，需在板端独立确认原 Nav2 目标已停止并
完成安全处置；当前 v1 没有自动解除未知目标阻塞的管理接口。
完整终态过期时转为永久 tombstone，同一 task ID 永不重用。

## 板端联调门槛

普通点位联调前确认 occupancy-editor 导出的 `~/.ros/waypoints.yaml` 使用 A–J 槽位 ID、
已由节点加载，并通过当前 `/map` 校验。随机目标 `11` 只要求实时 `/map` 有合格空闲区。
既有英文 ID 的地点文件须先迁移，
不能直接用新编辑器读取；旧 Action 的 `waypoints.yaml` 是另一种格式，
不能直接替代。Nav2、Action 和本包都应在地图与点位准备好后再联调。

重启恢复需验证：QUEUED 落盘后崩溃、DISPATCHED 落盘但发送前崩溃、
Nav2 接收 Goal 后响应落盘前崩溃、取消与发送竞争、取消与成功竞争、
UUID 查询返回 `STATUS_UNKNOWN`、重启后按 UUID 取到真实结果或定向取消。
这些板端测试完成前，不声称重启恢复已通过。
