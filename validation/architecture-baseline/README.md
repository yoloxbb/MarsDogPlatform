# 架构基线落地与验证记录

2026-10-12，板端 `/home/marsdog/MarsDogPlatform`，Ubuntu 22.04.5 / ARM64，源码基点 `c21c3bf`，分支 `codex/reusable-local-motion`。开始时已有未提交的动作、导航和工程工具修改；本轮在其上增加开发文档、流程模板和能力证据。

## 交付范围

- [当前系统基线](../../docs/architecture/SYSTEM_BASELINE.md)、[五人责任表](../../docs/OWNERSHIP.md)。
- [能力基线](../../docs/architecture/CAPABILITY_BASELINE.md)、原生成工具的 [详细快照](capabilities.json) 和 [路由表](CAPABILITY_ROUTES.md)。
- [工程规范](../../docs/development/ENGINEERING_STANDARD.md)、[功能规格模板](../../docs/development/templates/FEATURE_SPEC.md)、PR 模板与原开发入口的关联。
- [叫过来与唤醒靠近规格](../../docs/development/scenarios/CALLER_APPROACH.md)、[后续任务及验收](../../docs/architecture/REFACTOR_ROADMAP.md)。

本轮没有修改业务实现、ROS 类型、默认运动配置、依赖锁或算法。代表场景仍保留 `visual_target_only_no_navigation_geometry` 拒绝边界，几何桥接与全系统控制权约束列为后续任务。

## 验证结果

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| `python3 -B tools/dev.py check` | 通过：17 个 ROS 包、25 个接口；平台 122 项，日志基础设施 13 项 | 静态边界、标识及原有工程回归 |
| 配置能力生成 | 125 条路由：49 缺模板，70 blocked，6 runtime_check_required | 默认 Lite3，无运行时覆盖；实机 unknown |
| Voice 选定单测 | 58 通过，0 skip | `tests/test_session_recovery.py`；加载 Humble，使用替身对象 |
| Vision 选定单测 | 11 通过，0 skip | `tests/test_visual_locate_task.py`、`tests/test_wake_target_snapshot.py` |
| BT 选定单测 | 52 通过，0 skip | `tests/test_voice_engagement.py`、`marsdog_behavior/tests/test_runtime_architecture.py` |
| Action 选定单测 | 16 通过，0 skip | `tests/test_person_nav_approach_adapter.py` |

四模块选定测试共 137 项，属于现有局部回归，不是 137 个端到端场景。它们没有启动真实相机、麦克风、运动执行或完整导航链路。导航 C++ 单测、DDS 集成、全量模块测试和远端 CI 不在本轮复跑范围。

初次直接运行 Voice/Vision 所选用例时，未加载 Humble 导致 rclpy 导入失败；在隔离环境加载既有 Humble 后重新执行通过。原尝试日志保留在板端 `out/architecture-rollout`，不以导入失败或跳过计作通过。

原始命令与计数见 [selected-tests.json](selected-tests.json)，JUnit、日志和生成结果的指纹见 [evidence-manifest.json](evidence-manifest.json)。可复现命令见场景规格。文档落盘后的检查结果另记录在同目录 `verification.json`。

## 下一项工程工作

先完成目标观测数据契约 B-01：target_id/epoch 与原始图像时间、bbox 原图坐标的绑定。Action 再通过已有 LocateFromBbox 服务取得几何目标，保留取消与迟到结果检查。具体接口和验收标准已在场景规格中列出；不得把几何替身成功提升为真实链路完成。
