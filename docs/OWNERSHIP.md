# 模块所有权与跨模块开发

团队由听觉、视觉、行为树、动作系统、SLAM 导航五位开发组成。目录和技术角色仍以
[platform/modules.json](../platform/modules.json) 为准；以下把这些技术角色映射到五人分工。
仓库已配置远端；真实成员账号、备份人及远端强制评审规则由团队绑定，本表不虚构 CODEOWNERS 身份。

| 团队角色 | 主责 | 兼任或共同责任 | 跨边界评审 |
| --- | --- | --- | --- |
| 听觉开发 | modules/voice | 音频事件、声纹与语音会话契约 | BT、Emotion 的相关消费方 |
| 视觉开发 | modules/vision | 目标身份、新鲜度、图像观测与坐标约定 | BT、Action、导航的相关消费方 |
| 行为树开发 | modules/behavior | Emotion/Needs 技术维护，保持 modules/emotion 独立 | 状态生产者、Action 及受影响感知 owner |
| 动作开发 | modules/action | 技能、阶段、执行生命周期、设备与控制资源接入 | BT、导航；运动控制权与导航共同负责 |
| SLAM 导航开发 | robotics/ros2/src | 定位、地图、TF、导航、避障、机器人 profile 与第三方来源 | Action、Vision；实际设备协议由设备提供方确认 |

Emotion/Needs 的数值、阈值和结算语义由明确的产品决策人决定，BT 兼任 owner 负责技术实现及回归。
兼任不授权 BT 直接修改另一个进程的状态，也不把 Emotion 并入 BT 的私有实现。

每个功能指定一位**功能负责人**，负责跨模块规格、进度和端到端结果。每个迭代或发布指定一位
**集成负责人**，在迭代记录或功能规格中填写姓名，负责环境组合、测试证据、发布清单和回滚。
tools、profile、契约、日志基础设施由当期集成负责人和受影响模块 owner 共同维护。
第三方固定版本与来源由 SLAM 导航开发牵头；各模块自己的模型和依赖仍归本模块维护。

同一人兼任多个角色时，跨模块接口仍由生产方、消费方共同评审；涉及新产品行为的语义须有明确决策。
尚未填写姓名不会妨碍普通模块开发，但功能或发布进入评审前必须写明实际负责人。

开发入口是本主仓。旧仓库保留为基线与恢复来源，不在两处同时修改同一实现。
独立模块的 pyproject、uv.lock、测试保持本模块所有；公共接口的修改同时审查
interfaces/registry.json 中的生产者与消费者。修改原有 ROS 类型身份、字段、取消
或结果语义时先做兼容性分析，不通过修改旧基线消除差异。

AI Agent 先读 AGENTS.md、docs/migration/STATUS.md、模块迁移记录，再执行对应模块测试。
运行 tools/check_architecture.py 检查导入边界、IDL 指纹和 package 依赖图；
跨边界功能增加公开接口的集成测试。禁止通过共享业务 common 或兄弟目录
私有 import 绕过接口。日志和进程编排工具只负责运行，不承担机器人决策。

仓库远端与当前开发入口见 [README](../README.md)。厂商库及模型的分发范围按原来源和许可记录处理；
不能因统一主仓而扩大公开范围。开发步骤见 [工程规范](development/ENGINEERING_STANDARD.md)，
新功能使用 [功能规格模板](development/templates/FEATURE_SPEC.md)。
