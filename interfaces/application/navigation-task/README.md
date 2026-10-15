# 导航任务公共接口

唯一入口是 `/navigation/task`，类型为 `marsdog_interfaces/srv/NavigationTask`。
状态使用 `/navigation/status`（std_msgs/msg/String），点位可视化使用 `/navigation/markers`（visualization_msgs/msg/MarkerArray）。
导航不再依赖 VoiceTask。旧入口、类型选择参数及双入口配置已删除，不提供别名。

请求字段与导航 v1 保持一致：task_id、task_type、params_json。
protocol_version 和 client_id 位于 params_json 内。
`goto_place` 返回受理结果；`query` 查询持久化状态；`cancel` 返回取消请求受理结果。
取消 ACK 不能释放运动所有权；必须等待真实终态。`release_recovery` 仍要求操作人员确认停止。
协议版本仍为 1.0；业务状态机、SQLite 数据和任务 ID 不作迁移或清空。
完整业务协议见 [航点接口](../../../robotics/ros2/src/waypoint_nav/docs/INTERFACE.md)。

部署时同时更新公共 IDL、waypoint_nav、Action、Behavior、UWB 服务与调用侧配置，并清除旧构建目录后重新编译。
现有部署不能混用新旧接口。回滚应整体恢复同一版本的生产者、消费者与配置；保留任务数据库及恢复锁。
迁移清单和验证入口见 [接口迁移说明](../../../docs/development/INTERFACE_MIGRATION_20261015.md)。
