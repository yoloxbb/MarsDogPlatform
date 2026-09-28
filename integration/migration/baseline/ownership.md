# Role ownership（实际账号 UNKNOWN）

| 模块/资产 | 负责角色 | 跨边界审查 |
| --- | --- | --- |
| Vision | Vision maintainer | 事件/服务消费者 |
| Voice | Voice maintainer | BT 会话消费者 |
| Emotion/Needs | Needs/Emotion maintainer | BT 结果结算 |
| BehaviorTree | Behavior maintainer | Action 生命周期、Needs 结算 |
| Action | Action maintainer | Navigation/硬件能力、取消与停止 |
| robot_ws 自研能力 | Robotics maintainer | Action/感知消费者 |
| RTAB/OpenVINS/VINS/vendor | Robotics/vendor maintainer | 来源、许可、ABI、回放 |
| contracts/integration/platform | Platform maintainer | 生产者与受影响消费者 |

这些是责任角色，不是假造的 GitHub team。实际 owner 账号尚未提供，因此暂不生成
无效 CODEOWNERS 条目。待绑定真实账号后，远端仓库保护规则才能执行强制审查。
当前 Technical Lead 承担迁移实现和自审；这不构成生产模块 owner 的人工验收。
