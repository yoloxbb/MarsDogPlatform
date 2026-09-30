# 五模块 R2–R4 重构验收 — 2026-09-30

**R1–R4 在授权的软件兼容性范围内全部完成。** 本目录记录 R2–R4 和最终组合回归；
R1 提交 66c7eaa 及 validation/compat-refactor/r1 保持不变。
进入本轮时主仓干净，分支 refactor/audio-contracts，基线
66c7eaa70da810bf1e0a19ab4475c2bd65267e21。之前的未提交工程改动已在 P7 保全并提交，
本轮没有 reset、stash、覆盖用户改动或重做迁移。

## 已完成内容

- Voice：会话/hold、识别与意图/KWS 协作、任务路由、服务 envelope。
- Vision：视觉快照/目标查询、事件派生、任务路由与服务 envelope。
- Emotion/Needs：领域内共用状态/信号发布，保留状态权威和结算。
- BT：声音校验、视觉缓存消费、状态/信号订阅、语音会话协调。
- Action：感知分发、goal 参数、反馈/结果消息、预约/lease/取消与执行协调。
- 统一接口查阅目录、冻结样例、独立进程契约、安装来源和依赖方向门禁。

旧 ROS/Python 入口保留，协调函数复用节点原状态和锁，不建立第二份状态。
60 个提取函数与 Git 基线主体 AST 一致（依赖注入替换逐项列明）。
Emotion 共用发布的四条真实路径验证了时间、顺序、Unicode、payload 不变和自动信号行为。
286 个受保护文件原字节保持，涵盖配置、锁、IDL、模型适配器、导航和第三方登记。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| 平台 | 71 tests 通过，含 14 个新增门禁失败/边界测试 |
| Voice Humble 完整单测 | 430 passed，0 skip |
| Vision | 289 passed，3 个 RGA 设备相关 skip |
| Emotion | 218 tests + 156 subtests，374 JUnit entries，0 skip |
| BehaviorTree | 533 passed，0 skip |
| Action 独立环境单测 | 423 passed，29 skip（20 ROS + 9 PySide2 GUI） |
| Action Humble 回调 | 35 passed，0 skip；精确覆盖上述 20 个 ROS skip，见 ros/skip-coverage.json |
| 声音契约 | 46 场景，真实 Voice → BT / Emotion |
| 视觉契约 | 7 组生产输出，33 场景分别进入真实 BT / Emotion / Action |
| 状态契约 | 7 组发布序列，34 场景进入真实 BT |
| 任务契约 | Voice / Vision 各 18 场景，36 份回调观测 |
| 原结果契约 | 25 passed；Action → BT → Needs 各自独立进程 |
| 五个 wheel | 离线缓存构建、新环境安装；18 个组件无 ROS 导入并与源码哈希相同 |
| ROS 安装 | 默认组合 15 包增量构建、doctor；25 个组件/包装文件安装字节与源码相同 |
| 默认 smoke | 当前安装节点 + 真实 DDS，全部受管进程正常退出 |
| DDS 取消 | 当前安装 BT adapter；ACK 后约 0.361 秒才收 Result；期间不能清理目标 |
| Action 退出 | SIGINT、SIGTERM 均观察到模拟零速度命令、退出码 0、PID 回收 |
| supervisor 生命周期 | 中断、重复启动拒绝、子进程崩溃传播和 PID 全部回收通过 |
| CI 配置 | 所有 YAML 无重复键，run 块通过 bash -n；没有 hosted 运行 |

回调与全量单测有覆盖重叠，不能把数字相加当作独立功能数量。
任务门禁可导入 Humble，但不启动节点或服务 DDS；实际服务通信由 smoke 补充。
DDS 取消门禁使用测试 server；Action 真实回调及安装退出另有证据。
smoke 使用已有 mock 感知、模拟导航与 Lite3 I/O，不代表真实模型或运动硬件验证。

## 基线、失败与来源

baseline-capture.json 证明 visual/state/task 的冻结输出取自运行时代码修改前，
并与对应 baseline.json 一致。正常门禁没有刷新基线选项。
测试控制时间/随机源，只去除明确的随机 ID 和记账时间；保留事件/结果、
候选顺序、状态、协议异常及副作用。每个进程报告自己的解释器、源码和 foreign import 检查。

中途 r3-emotion 有一项旧测试失败：它按源码中时间包装函数的文字出现次数判断发布路径。
拆分后改为实际调用两种节点的状态/信号方法，核对时间、顺序和 payload；
全量重跑通过。失败报告保留在 intermediate/emotion-before-test-update，
没有删除断言来隐藏行为差异。制作状态测试输入时，将无效的 ISO 虚拟起点改为原 API
支持的 HH:MM，不修改运行时代码或扩大接口。

commands 保存 36 次命令的时间、HEAD、未提交状态、退出码和完整输出。
运行时 HEAD 尚是基线，实际新源码由 tested-module-hashes.json 的 588 个文件哈希标识，
不能将未提交的新实现误称为旧 HEAD 的测试结果。ros/installed-source-hashes.json
和 wheel 报告另记录安装内容来源。中断/崩溃注入的预期单次 FAIL 被保留，
以门禁确认正确传播失败和回收，而不是修改成成功。

原模型质量失败、P7 源码包及历史验收均保留。没有模型精度、实机、ARM/NPU、
扩展 Nav2/SLAM 或 hosted CI 验收；没有修改导航/避障内部，也未重新生成旧 P7 包。
下一步是按真实功能需求开发，不再把 R2–R4 作为未完成待办。

manifest.json 对本目录其余文件记录 SHA256。
复现入口见 docs/development/WORKFLOW.md 与 interfaces/application/README.md。

三份中间失败输出的展示副本仅去除行尾空格；原始字节保存在同路径 .gz，
对应哈希见 log-normalization.json。其余采集日志保持原字节。
