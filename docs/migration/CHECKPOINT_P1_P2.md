# P1 / P2 迁移验收记录

日期：2026-09-28。P1 基线和首条契约链已建立；P2 Emotion 软件迁移通过。
整个平台、完整 Action ROS 构建和实机验收尚未完成。

## 基线与历史

- 七个原仓 HEAD、index、tracked 内容/权限和非忽略工作区状态保持不变。
- 固定 3,074 个 tracked 文件、38 个 ROS package.xml、48 个 msg/srv/action 定义。
- Emotion 的 19 个 reachable commits、全部 refs 通过 bundle 恢复、fsck 和 refs 比较。
- 102 个原文件在前缀导入时内容和权限完全一致。原始对象留在 bundle/原仓，导入 SHA 因路径变换而变化，映射随新主仓保存。
- 当前只导入 Emotion。其余六库历史尚未归档导入。

## 验证结果

| 检查 | 结果 | 实际范围 |
| --- | --- | --- |
| 旧 Emotion | 346 JUnit cases 通过 | 190 tests + 156 subtests，无 ROS |
| 旧 BT | 528 通过 | 两个原测试目录，无 ROS |
| 旧 Action | 414 通过 / 29 skip | 缺 PySide2 / rclpy 的测试未执行 |
| P1 契约/基线 drift | 17 通过 | 13 结果链用例 + 4 drift 用例；三业务模块各自进程/环境 |
| 旧 Python wheel 干净安装 | 三个包构建可完成，默认使用失败 | packaging.json 保留缺配置/入口的真实失败 |
| 旧 ROS Emotion/BT | 构建通过 | 独立 setuptools 59.6 / Humble 工具链 |
| 旧 ROS Vision/Voice | 构建通过 | 只证明构建；模型和设备未启动 |
| 旧完整 Action ROS | BLOCKED | 缺 nav2_msgs 等外部依赖 |
| ExecuteBehavior DDS | 通过 | 原 IDL 实际生成、两进程 fake server/client；反馈、成功、取消 ACK 与终态分离约 0.361 秒 |
| 新 Emotion | 350 JUnit cases 通过 | 194 tests + 156 subtests，其中 4 项新增配置路径回归 |
| 旧 Action/BT → 新 Needs | 17 通过 | 保留 metadata、失败、中断、超时、去重、默认结算语义 |
| 新 Emotion wheel | 通过 | 非源码 cwd、六个入口、原配置 SHA 相同；无 ROS/无 PyYAML |
| 新 Emotion ROS | 构建与 installed node smoke 通过 | 六个原 ROS 可执行入口；新旧实际 Needs 节点经 DDS 收结果并发布状态 |
| ROS 新旧状态对照 | 通过 | Energy 启动 0；energyValue 88 结算为 12；相同 event_id 改为 42 仍保持 12 |

DDS Action fake server 不是生产 executor。Needs smoke 启动真实节点，但输入仍为合成事件；
所有话题重映射到测试前缀，独立 localhost domain，无设备或运动调用。
静态 imports 边界扫描通过，不保证所有动态 imports 或真实部署图都已覆盖。

## 实现边界

新 Emotion 仅补 pyproject build/scripts/dev lock，以及普通 wheel 的 sys.prefix/share
配置回退。源码配置和 ROS share 的优先级保留。未改需求算法、配置字节、namespace、
ROS package/端点、消息格式、取消/中断语义。没有创建 marsdog_interfaces。

门禁按可独立验证模块执行：Action 的环境缺口不阻塞 Emotion。各模块导入/软件验收
与生产切换分开记录，不把 P2 通过解释为整机已可部署。

## 保留的失败尝试

- setuptools 79 与 69 的 ROS 构建失败日志保留，最终使用独立 Humble 59.6 工具链。
- 从主仓根目录直接运行 Emotion 旧测试时，development tools import 失败；改为原有模块 cwd 运行，未改业务实现来绕过测试。
- ROS smoke 第一版夹具缺 action_type/demand_type，新旧节点都拒绝结算；修正测试为实际 BT 协议后通过，旧记录位于 p2-probe-fixture-correction。

详细命令、解释器和日志在同目录 module-checks.json、packaging.json、ros-checks.json、
humble59/ros-checks.json、ros-transport.json、p2-emotion-ros.json，以及对应 JUnit 文件。
更广泛风险及责任角色见 migration/baseline/known-gaps.md 与 ownership.md。
