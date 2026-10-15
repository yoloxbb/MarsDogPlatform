# waypoint_nav 点位导航服务

本包将地点 ID、精确名称或随机目标提交给 Nav2 `NavigateToPose`。它负责请求校验、同一时刻一个任务、状态发布、SQLite/WAL 持久化、取消确认和重启恢复；语音理解、任务仲裁、到点后的行为以及地点编辑网页位于其他模块。

完整请求、响应、状态机和错误码见 [接口协议](docs/INTERFACE.md)。

## 输入与输出

| 接口 | 默认名称 | 类型/来源 |
| --- | --- | --- |
| 上层服务 | `/navigation/task` | `marsdog_voice_interaction/srv/VoiceTask` |
| 任务状态 | `/navigation/status` | `std_msgs/String`，JSON |
| 地点标记 | `/navigation/markers` | `MarkerArray` |
| 实时地图 | `/map` | `OccupancyGrid`，含普通地点地图绑定校验 |
| 下层导航 | `/navigate_to_pose` | Nav2 Action |

服务和话题在源码中使用相对名称，表中为根 namespace 下的默认解析结果；Nav2 Action 名可由节点参数覆盖。

支持 `goto_place`、`query`、`cancel`、人工 `release_recovery`。生产调用方默认限定为 `marsdog_action_executor`，协议版本 `1.0`。普通地点只精确匹配 ID/名称，不做模糊搜索；`11` 和 `K` 是同一个随机目标保留入口，从实时地图的空闲区生成 Pose，不写入地点文件。

## 运行与存储

按 [公共构建说明](../../README.md) 选择 `waypoint_nav`，先准备 `modules/voice` 生成的 VoiceTask 接口和 Nav2。加载安装环境后：

```bash
ros2 launch waypoint_nav waypoint_nav.launch.py \
  waypoints_file:=$HOME/.ros/waypoints.yaml random_clearance_m:=0.35
```

该 launch 只启动 `waypoint_nav_dispatcher`，不会启动 Nav2 或地图服务。默认 SQLite 文件为 `~/.ros/waypoint_nav.sqlite3`，终态保留至少 86400 秒，取消确认预算 5 秒；这些是节点参数，不是该 launch 已声明的命令行参数。需要调整时使用节点参数或自定义 launch。

地点 YAML 与外部 occupancy-editor 输出格式一致，必须与当前 `/map` 的 frame、分辨率、尺寸和 origin 匹配。例如结构为：

```yaml
version: 1
frame_id: map
map: example.pgm
resolution: 0.05
origin: [-10.0, -10.0, 0.0]
size: [384, 384]
waypoints:
  - id: A
    name: 客厅
    pose:
      position: {x: 1.625, y: -0.525, z: 0.0}
      orientation: {x: 0.0, y: 0.0, z: 0.2948, w: 0.9556}
```

这只是格式示例，不能直接用于未匹配的真实地图。网页固定 A–J 槽位约定见协议；本包不生成网页。

## 取消与恢复

取消 Service 的 `success=true` 只表示受理。必须等待原任务真实终态；不能把取消 ACK 当成底盘已停止。无法确认 Nav2 Goal 终态时进入 `RECOVERY_REQUIRED` 并阻塞新导航。

人工确认机器人已停止后，操作员可使用 `release_recovery`，严格提供 JSON 布尔值 `operator_confirmed_stopped=true`；该字段是人工声明，不是鉴权或物理停车检测。普通 cancel 不会解除恢复锁，自动客户端不得生成此人工操作。成功释放记录 `INTERRUPTED/RECOVERY_RELEASED`，不会伪装为导航成功。

重启恢复和实机运动仍需按协议末尾场景验证；本次文档核对没有运行这些测试。
