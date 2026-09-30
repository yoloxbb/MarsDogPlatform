# 模块所有权与跨模块开发

当前没有配置远端仓库或真实 owner 账号，CODEOWNERS 尚不执行强制审查。
角色清单以 platform/modules.json 为准；第三方由 Robotics/vendor maintainer 负责，
tools、profile、契约和集成由 Platform maintainer 与受影响模块 owner 共同负责。

开发入口是本主仓。旧仓库保留为基线与恢复来源，不在两处同时修改同一实现。
独立模块的 pyproject、uv.lock、测试保持本模块所有；公共接口的修改同时审查
interfaces/registry.json 中的生产者与消费者。修改原有 ROS 类型身份、字段、取消
或结果语义时先做兼容性分析，不通过修改旧基线消除差异。

AI Agent 先读 AGENTS.md、docs/migration/STATUS.md、模块迁移记录，再执行对应模块测试。
运行 tools/check_architecture.py 检查导入边界、IDL 指纹和 package 依赖图；
跨边界功能增加公开接口的集成测试。禁止通过共享业务 common 或兄弟目录
私有 import 绕过接口。日志和进程编排工具只负责运行，不承担机器人决策。

远端名称、owner 账号和是否公开必须由团队提供；未提供前不推送或公开厂商库。
