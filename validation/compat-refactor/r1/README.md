# R1 兼容性验证 — 2026-09-30

基线：3f50614721419befddc4c59b218571ea95a5ddb1。进入工作时主仓干净；
分支 refactor/audio-contracts。本轮仅提取 BT 的两个无状态声音校验函数，
保持原方法入口、日志对象和时钟；语法树对比与 46 个跨模块场景均一致。

| 检查 | 结果 |
| --- | --- |
| 新声音契约 | 46 个场景，真实 Voice/BT/Emotion 独立进程；重构前后完全相同 |
| 平台 | 57 tests，其中新增 6 项门禁失败/来源测试 |
| BT | 533 passed，0 skip |
| Emotion | 218 tests + 156 subtests；374 JUnit entries，0 skip |
| Voice Humble 完整单测 | 430 passed，0 skip；没有运行模型/麦克风 |
| 原 Action→BT→Needs 契约 | 25 passed |
| 干净 BT wheel | 离线缓存构建/新环境安装/入口/7 配置哈希通过 |
| ROS 默认组合 | 15 包增量构建、doctor、真实安装进程与 DDS 的模拟 smoke 通过 |
| 退出 | 所有 11 个受管进程退出码 0，无强制回收，PID 已消失 |
| 保护范围 | 68 个锁/manifest/配置资产字节未变；IDL/robotics/config/vendor 无 diff |

首次 wheel 在线检查因 PyPI 连接超时失败，保留在 commands/behavior-wheel；
UV_OFFLINE=true 使用原有缓存后通过，同一依赖版本，没有通过修改版本规避问题。
构建 stderr 是禁用 byte-compiling 的已有警告。初始核对脚本曾未处理 Git 对中文路径
的转义，已改用 NUL 分隔重新核对；未因此修改任何资产。

commands 保留命令、工作目录、当时 HEAD/未提交状态及输出；summary.json 的
tested_file_sha256 对应本轮实际测试源码，避免把运行时未提交改动误算为旧 HEAD。
audio 保留跨进程来源与结果；extraction-proof.json 记录机械提取等价检查；
ros/smoke 使用明确的感知、导航、设备替身，不属于实机或真实感知质量验收。
ROS 配置和取消/结算语义均未变，GO_HOME 沿用不产生 Needs 结算的规则。

本片不重复运行未改源码的 Action/Vision 单测，不重复迁移或 Nav2/SLAM 扩展验收。
新的 CI job 仅完成配置与本地等价命令验证，没有 hosted CI 记录。
R2–R4 后续切片见 docs/architecture/COMPATIBILITY_REFACTOR.md。

manifest.json 对此目录所有其他证据文件记录 SHA256。原 P7 证据和源码包保持原样。
