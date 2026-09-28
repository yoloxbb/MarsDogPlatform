# 已落地架构与迁移自审

2026-09-29。原提案是历史决策快照；当前状态以 STATUS.md 与本文件为准。

| 旧来源 | 当前权威开发位置 / 保留方式 |
| --- | --- |
| MarsDog | modules/vision，32 个历史提交 |
| MarsDogVoiceInteraction | modules/voice，23 个可达历史提交 |
| MarsDogEmotion | modules/emotion，19 个历史提交 |
| 20260702_MarsDogTree | modules/behavior，7 个历史提交 |
| 20260707_MarsDogAction | modules/action，5 个历史提交 |
| robot_ws 自研 ROS 能力 | robotics/ros2/src，30 个相关历史提交、122 个文件；完整 31 个提交另行归档 |
| robot_ws 内 OpenVINS / VINS / UWB | third_party/sources.lock.json → .external，原始字节与模式校验 |
| rtabmap_ws | 整个定制 fork 保留为外部固定快照，完整 4 个提交归档 |
| 新增 marsdog_interfaces / waypoint_nav | interfaces/ros2 / robotics/ros2/src；独立冻结非 Git 来源基线 |

robotics/ros2/src 采用一个清晰的 ROS package 根目录，代替提案示意图中分开的
modules/navigation 与 modules/sensors；包名和内部结构保留，构建只显式选择所需包。
没有把旧工作区整体递归 colcon build，也没有把第三方算法复制成自研。

五个模块保留独立 uv.lock 与解释器。Emotion/BT 增加 ros 可选依赖 NumPy 1.26.4，
解决实际 Humble 生成消息导入失败；Action 仍为 NumPy 2.2.6，Vision/Voice 仍为 1.x。
构建工具独立使用 Humble 的 Python 3.10 ABI。本机 profile 固定 Cyclone loopback 配置，
保留旧生产默认 RMW。没有合并成单一 lockfile 或运行进程。

BT 选择/抢占目标；Action 执行目标内阶段并管理终态；Needs 独立结算；
Voice/Vision 通过原有 ROS 事件与 task service 提供输入/能力。事件反馈环保留，
实现导入与 ROS package 依赖检查禁止新增循环。没有新增全局 RobotState 或通用业务 common。
公共 ExecuteBehavior 使用真实提供的 marsdog_interfaces；VoiceTask/VisionTask 类型位置不改。
航点借用 VoiceTask 属于登记过的兼容接口，不借迁移更换类型。

本机入口 tools/marsdog.py 只做环境、配置、进程生命周期和验收编排。
它不是在线业务仲裁者；单机 supervisor 的退出会关闭其启动的组合，这是开发启动行为，
不声称具备机器人高可用或急停能力。模块仍能单独构建、测试和启动。

开发替身仅替代缺少的外部输入：相机图像、地图/Nav2 与 Lite3 I/O。
Lite3 仍走现有 backend 的预检和规划；不建立不存在的控制器或嵌入式协议。
原有未验证动作仍会被拒绝；未启用的视觉接近/唤醒转向会返回 controller_required，
不会为了显示“成功”绕过这些保护。本机 smoke 只声明 go_home 场景及通道连通成功。

自审结论：

- 没有为了合仓新增业务中间层；manifest、registry 和构建清单各自负责不同信息。
- 源码、消息类型、配置资产和迁移例外均可追溯；静态检查不能解析任意动态 import，保留这一限制。
- 第三方初始导入相对上游的完整改动仍 UNKNOWN；不能用上游最新版替换本地定制快照。
- 历史脚本、legacy launch 和未确认生产用途的代码继续保留，未自行退役。
- Voice 历史内已有的 ARM 厂商库为迁移例外，未新增副本；许可确认前不发布公开制品。
- 所有远端 CI、CODEOWNERS 身份、生产镜像和硬件验收仍未配置，不能当成本机验收已覆盖。
- 统一入口减少日常协调成本；跨模块改动以接口 registry、独立回归与集成 smoke 约束。

本轮窄范围修复：Vision wheel 资源、原生 C++ 两处语法错误、Action 外部配置/
显式本机 I/O、Voice mock 命令覆盖/可选 catalog ID、BT 有效 ROS context 内退出、
ROS 依赖声明。先前批准的导航恢复与电量证据策略见各独立迁移记录。
