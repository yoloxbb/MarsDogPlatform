# 命名与配置整理验证（2026-09-30）

基线为 `docs/event-behavior-action` 的 `0c97e42`，工作区起初干净。
本轮在 `refactor/naming-contracts` 上完成兼容整理；未重新迁移仓库，未调整模型或导航避障实现。

变更说明和后续新增功能步骤见 [命名规范](../../interfaces/naming/README.md)。
机器结果见 [result.json](result.json)，来源摘要包含本轮代码/配置文件哈希。

## 本轮变更

- 增加由七份原配置生成的标识目录、命名空间规则、精确兼容例外及引用检查。
- `dev.py check` 保持仅标准库依赖；CI 的 Action job 使用独立环境做实时 YAML 对照。
- 去掉意图池 49 组从未被候选选择读取的 aliases，保留实际使用的旧输入兼容表。
- 四个进食行为共享 YAML 阶段定义；Action 加载器按行为深拷贝，避免可变对象交叉污染。
- Voice 内部局部变量区分产品动作标签，保留词库键、AudioEvent 字段和全部既有标识。
- 原迁移字节基线未改。三份已整理 YAML 使用从原提交导出的有效内容哈希；
  其余默认资源和 ROS IDL 继续严格比较原字节。负例覆盖真正修改候选、动作或 command_id。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 平台架构与回归 | PASS；15 ROS package、21 接口；92 项测试 |
| 标识静态检查、refresh、live | PASS_WITH_KNOWN_GAPS；125 声明路线、82 词库命令、116 意图池、74 Action 模板、183 Unit |
| YAML / 语义兼容负例 | 4 项通过，含重复键、锚点、目录一致性及三份配置变更拒绝 |
| Behavior | 533 通过 |
| Voice Humble 单测 | 430 通过，无跳过；非麦克风/模型/DDS 测试 |
| Emotion | 374 通过 |
| Action 纯单测 | 424 通过、29 明确跳过（ROS / PySide2 依赖缺失） |
| Action ROS 回调 | 35 通过、无跳过；真实回调 + fake collaborators |
| Audio / State / Result 契约 | 46 / 34 / 25 通过；固定兼容预期保留 |
| Action / Behavior / Voice wheel | 全部通过；干净独立环境、源码外加载、配置/媒体哈希、入口验证 |
| ROS build / doctor | 15 package 构建成功；五模块从当前安装导入成功 |
| 配置等价性、Markdown 链接、git diff --check | 通过 |

Action 的 29 个纯环境跳过项未计入通过数；35 项独立 ROS 回调检查提供相应回调覆盖，
GUI 仍无验证。本轮没有硬件、真实模型精度或现场 ASR→动作验收，也没有把 CI 配置当作远端已运行证据。

## 明确保留的问题

49 条配置路由仍缺少 Action 模板；按事件、上下文、下游名精确登记，
不会自动改名、映射成近似动作或伪装成功。

5 个词库事件没有本表直接行为路由，5 个 BT 音频入口不在词库；
它们是声明配置图的边界，不能据此推断代码路径不可达。33 个候选池未被声明路线选取，
其中包括内部续接和显式覆盖；未作为死代码删除。

本地完整日志位于主仓的 `out/naming-contracts/`，安装日志及结果位于
`out/{action,behavior,voice}-install/`，ROS 构建/导入记录位于 `out/local/`。
