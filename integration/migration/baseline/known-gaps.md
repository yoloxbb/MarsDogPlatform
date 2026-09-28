# 已知缺口（2026-09-28）

| 编号 | 观察和证据 | 状态/处理边界 |
| --- | --- | --- |
| G01 | P1 Action CMake 缺 nav2_msgs；marsdog_interfaces、unitree_api、unitree_go、transfer_interfaces 未安装 | P3 使用本地校验解压的官方 Nav2 消息制品后，新旧完整包构建通过；底盘运行仍未验收，不造替代协议 |
| G02 | BT/Action 首选外部 marsdog_interfaces，本机无此包；boundaries.json 记录现有 fallback | 真实部署类型 UNKNOWN；不创建同名公共包触发隐式切换 |
| G03 | /waypoint_nav/task 和 /waypoint_nav/status 的真实 server 不在已确认代码中 | provider UNKNOWN；mock 只能覆盖契约，不能验收导航 |
| G04 | 旧 Emotion wheel 缺六个脚本，默认配置路径不能解析 | 在新主仓 P2 修复，原源码和旧失败证据保留 |
| G05 | 旧 BT wheel 缺 behavior_tree_node，默认配置路径不能解析 | 新主仓 P3a 已修复；532 回归、干净安装、ROS build/adapter smoke 通过 |
| G06 | 旧 Action wheel 缺 share/config，包括 config 内资源；默认 ConfigLoader 报九个 yaml 缺失 | P3b 已修复安装、入口和资源回退；34 个原配置/媒体文件 hash 保持一致 |
| G07 | setuptools 79 在 Humble colcon Python 包识别失败；69 仍有元数据兼容错误；59.6 可构建 Emotion/BT | 固定独立 Humble 构建工具环境；现代 wheel 构建使用隔离 backend |
| G08 | Action 原测试 29 项 skip：9 PySide2、7 rclpy unavailable、13 rclpy not installed | 不计为通过；需后续对应运行环境验收 |
| G09 | 真模型、音频设备、NPU、地图/轨迹、底盘/停止/充电真值未运行 | P4/P5/P6 验收项，软件回归不能替代硬件 |
| G10 | 真实 launch/profile、外部接口版本、远端/owner 身份未知 | 已向用户请求生产事实；不阻塞可独立验证的小步迁移 |
| G11 | 本机默认 Fast DDS 传输在旧新包上均出现发现后 SendGoal 不达；精确根因 UNKNOWN | 单独记录，loopback UDP 仅测试配置，不修改生产传输；不能据此宣称整机 ROS 联调通过 |

所有本文件所引 JSON 均位于 migration/reports/p1-20260928。结果只对应所记录
HEAD、主机和环境。现有缺失电量默认 100、部分中断仍结算等规则是兼容基线；
本阶段不把这些行为改成另一种产品语义。
