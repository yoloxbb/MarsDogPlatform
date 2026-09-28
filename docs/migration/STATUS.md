# 当前迁移状态 — 2026-09-29

**Lite3 本机 CPU 软件集成目标已通过；生产硬件发布尚未完成。**
最新可复现入口为 tools/marsdog.py，运行说明见 ../LOCAL_LITE3_CPU.md。
此前本文件的累积进度保留在 Git 历史；以下为当前唯一状态表。

| 阶段 | 当前状态 | 证据 |
| --- | --- | --- |
| P0/P1 架构与原始基线 | 完成；七个原仓库未修改 | architecture 提案、integration/migration/baseline、validation/local-platform/original-sources.json |
| P2 Emotion/Needs | 历史/独立环境/安装/ROS 完成 | 19 提交；本轮 218 tests + 156 subtests；P2_EMOTION.md |
| P3 BehaviorTree | 历史/接口/安装/集成完成 | 7 提交；本轮 533 tests；退出 context 缺陷已修复 |
| P3 Action | 历史/接口/安装/集成完成 | 5 提交；423 pass / 29 skip；显式本机 Lite3 I/O 与外部配置，生产默认不改 |
| P4 Voice | 历史/安装/ROS 完成 | 23 提交；本轮 367 tests；修复 mock 命令覆盖，新增可选 catalog ID |
| P4 Vision | 历史/资源/CPU 环境/ROS 完成 | 32 提交；280 pass / 3 RGA skip；真实模型与相机未验收 |
| P5 新接口与航点 | 完成软件门禁 | 导航 31 tests + 2 subtests；取消/重启/终态恢复、公开类型与 Energy 证据策略 |
| P5 Native ROS | 自研包历史/CPU 构建与功能回归完成 | 30 相关提交、122 文件；8 包构建，140 JUnit cases、13 CTest entries 全通过；两组计数有重叠 |
| P5 Third-party | 固定、归档、恢复和校验完成 | 完整 robot 31 / RTAB 4 提交；.external 快照；上游完整 delta / 部分许可 UNKNOWN |
| P6 本机集成 | prepare/build/doctor/up/smoke/退出与故障测试完成 | 15 包组合构建；10 进程 + probe 正常关闭；同 interaction/goal 关联的 GO_HOME 成功；lifecycle.json |
| P6 契约与工程门禁 | 完成当前软件范围 | 25 契约/基线检查（15 跨进程用例 + 10 guards）；15 ROS manifest DAG；21 登记接口 |
| P6 生产发布 / 远端 CI | 未验收 / 未配置 | 缺设备、模型、真实 Nav2/运控/电池来源与远端/owner 身份 |
| P7 旧代码退役 | 未进行 | 不确定生产用途的代码/launch/脚本继续保留，不删除原仓 |

本机真实链路：
Voice mock → audio_event → BT → marsdog_interfaces/ExecuteBehavior → Action
→ waypoint_nav/VoiceTask → 模拟 NavigateToPose → Lite3 backend 模拟 I/O → SUCCESS。
Vision 事件、Voice/Vision 服务、Needs/Emotion 状态同时验证。
go_home 是语音命令，按现有规则不产生 Needs 结算事件。Energy 独立契约门禁验证
拒绝模拟/陈旧/旧标量电量；当前没有 BMS 观测生产者。

稳定性验证包含主动 SIGTERM、重复启动、Action 进程崩溃、清理全部自有 PID。
故障注入那次运行的 FAIL 是预期结果，lifecycle 门禁验证 supervisor 正确失败退出。
默认 Fast DDS 在本机的已知传输问题没有被冒充解决；本机 profile 明确使用验证过的
Cyclone + loopback + 小分片。未修改系统网络或旧生产 RMW。

继续工作需要真实输入的范围：

- 提供模型文件及版本/哈希后验证真实 CPU 推理与音频/图像回放。
- 提供 Lite3 设备侧接口包、部署配置和硬件环境后验证运动、控制权、停止和状态。
- 提供实际相机/IMU/地图输入后构建验收完整 Nav2、RTAB/OpenVINS 组合与性能。
- 确认远端地址、owner 账号、厂商库分发许可后才能发布、绑定 CI/保护规则。
- 不擅自退役 legacy 入口，不猜测运控/嵌入式/BMS 实现。

当前没有需要通过放宽断言或修改旧基线掩盖的已接受失败。历史试验失败与未验收范围
均保留记录。正式源码与运行证据见 validation/local-platform/release-manifest.json。
