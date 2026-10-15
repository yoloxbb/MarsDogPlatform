# MarsDog 能力基线与交付状态

2026-10-12 从板端当前工作区的原配置生成，使用现有 `tools/capabilities.py`，选择默认 Lite3，未传运行时覆盖。配置状态、软件验证、指定板端运行和实机验收分别记录。当前快照不代表在线 ROS 图或部署覆盖后的能力。

## 当前配置清单

| 项目 | 数量或状态 |
| --- | --- |
| Voice 词库命令 | 82 |
| 声明式事件路由 | 125 |
| Intent 候选池 | 116 |
| Action 行为模板 | 74 |
| Action Unit 登记 | 183 |
| 缺少下游模板的路由 | 49 |
| 当前配置策略阻断的路由 | 70 |
| 仍需运行时条件判断的路由 | 6 |
| 实机验收 | unknown |

49、70、6 是本次所选默认配置下互斥的路由分类，共 125 条。它们不等于 125 个独立产品功能；代码专用会话路径不完全包含在声明式目录中。183 个 Unit 登记也不等于底盘支持 183 个动作。

完整快照包括配置哈希、每条路由、阶段和门限：[capabilities.json](../../validation/architecture-baseline/capabilities.json)。
按路由浏览：[生成的能力表](../../validation/architecture-baseline/CAPABILITY_ROUTES.md)。

## 如何判断可交付

| 维度 | 状态与所需证据 | 维护者 |
| --- | --- | --- |
| 配置引用与门限 | missing_template / blocked / runtime_check_required；由现有工具生成 | BT 与 Action |
| 软件逻辑及通信 | NOT_RUN / PASS / FAIL / 明确跳过；记录单测、契约和 DDS 各自范围 | 功能负责人汇总，各模块提供 |
| 指定板端环境 | 记录 ARM64 源码安装来源、overlay、profile、模型及回放结果 | 集成负责人 |
| 指定实机场景 | 记录机器人、设备、标定、场景、运动结果与停止证据 | 集成负责人及相关模块 |

这些维度分别更新，不合成一个容易误解的“全通过”数字。已有模板通过配置检查仍可能因目标、姿态、设备或几何数据不足而执行失败。

## 首批关注能力

| 能力 | 已知事实 | 剩余工作与负责人 |
| --- | --- | --- |
| 明确口令叫过来 | `come_to_owner` 模板存在，配置状态为 runtime_check_required；当前视觉目标结果被 Action 明确拒绝导航 | Action 牵头连接受验证的三维定位边界，Vision/导航协作，BT 验收整条链路 |
| 唤醒后靠近说话人 | `approach_voice_caller` 模板存在，声纹、会话与目标锁规则已存在；同样受几何接入断点限制 | 与叫过来共用几何能力，但保持各自身份和会话语义 |
| 回家 | 历史隔离组合有模拟导航/真实 Nav2 加模拟输入的验证记录；不结算 Energy | 当前板端地图、定位、设备与配置另行验证 |
| 跟随、漫游和局部运动 | 已有 UWB 链路；新增 robot_local_motion 默认关闭并有独立 overlay | 导航和 Action 确定实际使用组合，验证控制权与停止，不自动切换默认路由 |
| 历史缺模板的 49 条路由 | 原兼容目录明确保留，当前不会因此得到真实动作实现 | BT 与 Action 按产品优先级逐项补齐或明确暂不交付，保留未退役的原入口 |

叫过来场景的失败边界和测试清单见 [场景规格](../development/scenarios/CALLER_APPROACH.md)。

## 更新方法

在仓库根目录运行：

```bash
python3 -B tools/capabilities.py --output out/capabilities
```

指定部署覆盖时增加 `--config-dir`、`--runtime-json` 和已支持的 `--chassis`，并记录实际参数；不要用 Lite3 快照推断其他底盘。详细说明见 [功能流程](../development/FEATURE_WORKFLOW.md)。

本目录快照作为该次架构基线保留。后续发布另存对应验证目录，将源码版本、配置哈希与结果关联；日常最新清单在 out 下生成。修复缺失路由后，先删除已解决的兼容例外，再按现有标识检查流程更新目录，不扩大例外掩盖新增缺口。
