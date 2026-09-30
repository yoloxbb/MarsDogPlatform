# 事件、意图、行为、动作与端点命名

本目录负责标识的含义、兼容例外和配置引用检查。各模块的原配置仍是运行时权威；
[catalog.json](catalog.json) 由工具生成供查阅，不被机器人加载，也不成为跨模块业务 common。
ROS 名称和类型仍以 [interfaces/registry.json](../registry.json) 为准，运行机制见
[事件到行为到动作详图](../../docs/architecture/EVENT_BEHAVIOR_ACTION.md)。

## 1 分清六类名称

| 对象 | 含义 / 所有者 | 新增名称约定 | 现有示例 |
| --- | --- | --- | --- |
| event / signal_event | 已识别的输入、状态边沿或生命周期事实 / 生产模块 | 保留所属族：EVT_VOICE_*、EVT_VISION_*、NEED_*、EMO_*；大写下划线，主体和语义明确 | EVT_VOICE_COMMAND_SHAKE_HAND |
| command_id | 语音命令身份 / Voice，BT 校验 | CMD_*；不要用其拼写推导行为名 | CMD_HAND |
| intent | 选择行为的语义入口 / BT | 小写下划线 | command_handshake |
| behavior_name | 可调度行为的身份 / BT 与 Action 契约 | 新增统一小写下划线；承诺要完成什么 | give_paw |
| unit_id | 行为阶段里的执行单元 / Action | ACT_* 大写下划线；描述具体执行能力 | ACT_INTERACT_GIVE_PAW |
| topic / service / action endpoint | 承载通信的通道 / ROS 接口所有者 | 延续已有领域路径、小写下划线，并登记 ROS 种类与类型 | /perception/audio_event、/execute_behavior |

Voice 词库的 `action_name: ACT_SHAKE_HAND` 是**产品动作标签**，不是 Action 的 unit_id；
`behavior` 是产品中文说明，也不是 BT 的 behavior_name。线上字段继续保留原名，
代码内部称为 product_action_label，目录采用独立命名空间，禁止靠 ACT_ 前缀跨层匹配。

握手链路依次为：
`EVT_VOICE_COMMAND_SHAKE_HAND → command_handshake → give_paw → ACT_INTERACT_GIVE_PAW`，
并校验 `CMD_HAND`。这些标识分属不同职责，不能因为目前一对一就删掉中间层。
一个意图仍可以选择多个行为，一个行为仍可以由多个阶段和动作构成。

事件命名不表达执行成功。行为发出、Goal 接受、阶段完成、结果结算是不同阶段；
新增功能必须遵守原有取消、抢占、身份去重、冷却和结算协议。

## 2 现有名字怎样保留

- 既有 camelCase 行为及 `ACT_SPLoot_LIE_DOWN` 按精确拼写兼容，逐项登记在
  [compatibility_exceptions.json](compatibility_exceptions.json)。新名字遵循新约定；
  不自动大小写转换，不用别名把两个能力当作同一个能力。
- `expressJoyWithHuman / Alone / InPlaceWithHuman` 等仍是独立行为身份：
  去重、冷却、目标、原地约束和续接依赖它们，不能只为缩短名字合并。
- 四个进食行为共用 YAML 阶段锚点；ConfigLoader 分别深拷贝模板，
  运行时可变对象彼此隔离。行为名和需求结算保持独立。
- 意图池原有未消费的 49 组 aliases 已移除（其中 14 组为空）。
  真正被 resolve_alias 读取的 `legacy_behavior_aliases.yaml` 保留；
  历史元数据可从 Git 的整理前提交 `0c97e42` 查阅。
- `EVT_STATE_CHANGED`、`EVT_VISION_FALL`、MASTER/FOLK/UNMASTER 等历史名称
  暂不改线上值。新增事件明确领域和主体；以后迁移旧事件需显式生产/消费兼容策略。
- PRAISE/SCOLD 是有界社交反应，不能把它们当作普通动作命令或直接修改情绪数值。

## 3 端点与类型

当前端点保留。不要为了统一英文外观同时改生产者、消费者、launch 和部署脚本。

| 端点 | 实际种类与语义 |
| --- | --- |
| /perception/audio_event | Topic，Voice 音频事件 envelope |
| /perception/visual_event | Topic，既有视觉事件及快照 envelope；快照不等于激活信号 |
| /emotion/state、/internal_need/state | Topic，状态与 signal_event；恢复/刷新不等于新事件 |
| /execute_behavior | ROS Action，Goal/Feedback/Result 与取消生命周期 |
| /behavior/result_event | Topic，当前由 BT 发布的 String JSON，限需求结算相关行为 |
| VoiceTask / VisionTask | 不同的 ROS service 类型；字段相似不代表可互换 |

`BehaviorResultEvent.msg` 是保留的历史 IDL，不能据其旧注释推断当前链路；
当前结果协议详见 [ExecuteBehavior 应用协议](../application/execute-behavior/README.md)。
导航沿用 VoiceTask 的兼容类型由其负责人后续处理，本轮不改。

## 4 自动目录和检查范围

`tools/identifier_catalog.py` 只读取七份 owning YAML，不 import 业务模块：
Voice 词库；BT 的 event_intent_map、intent_action_pool、behavior_categories、
emotion_behavior_map；Action 的 behavior_tree_actions、action_catalog。

目录记录每条声明路由的上下文、BT 名称、executor_behavior_name 覆盖后的下游名称，
情绪人物/独处/语音等待路线、社交情绪引用、动作阶段及 unit_id。
产品标签和 Unit ID 分开登记，不要求二者同名。

检查覆盖：

1. 目录来源哈希（含生成器本身）是否最新。
2. Voice/BT 在词库交集中的 command_id 是否一致；候选池、分类、情绪反应和 Unit 是否存在。
3. YAML 重复键、Voice 重复标识、阶段重复 ID、空候选、未登记的新拼写与悬空下游引用。
4. 兼容例外必须精确匹配当前问题；新增问题不会自动登记，已解决问题遗留的例外也会失败。

当前保留 **49 条缺少 Action 模板的配置路由**，检查结果明确为
`PASS_WITH_KNOWN_GAPS`。这表示兼容基线未退化，不表示这些功能已实现。
默认 Action 对相应未支持名称仍会拒绝，不替换为“相似动作”。

另外分别登记 5 个没有本表直接路由的词库事件，和 5 个没有词库记录的 BT 音频入口。
它们属于配置图边界，不能仅凭这个目录判断为无效命令；规则、模型、会话和门控代码
仍由原有 audio/state/result 等运行时契约测试验证。未被声明路线选择的 33 个候选池也会列出，
其中包含内部续接和显式行为覆盖，**不等于可以删除的死代码**。

本工具不证明事件一定能通过授权、设备支持动作、模型识别准确、部署覆盖配置有效，
也不替代取消与结算测试。它不扫描任意 Python 执行路径或导航实现。

## 5 新功能开发步骤

先在所属模块实现输入、行为或动作，并更新对应原配置；复用已有标识时不要另造同义名字。
如果新增动作需要硬件实现，能力验证另行完成，静态目录不制造成功证据。

在主仓根运行：

~~~bash
# 已有 Action 独立环境只提供 PyYAML 解析器；不加载其业务运行时。
python3 -B tools/check_identifiers.py --refresh --python modules/action/.venv/bin/python
python3 -B tools/dev.py check
python3 -B tools/check_identifiers.py --live --python modules/action/.venv/bin/python
modules/action/.venv/bin/python -B -m unittest discover -s integration/naming -v
~~~

普通 check 只需标准库，适用于尚未准备模块环境的 checkout；
refresh/live 才使用显式选择的模块 Python。工具不会安装依赖或修改例外列表。

refresh 只有检查通过才写 catalog；失败时先修配置。确实需要保留的兼容差异必须逐项评审，
不能为让门禁通过批量重建例外。补齐历史缺口时同时删除对应例外再刷新。
提交原配置与生成目录的 diff，并运行 [开发测试矩阵](../../docs/development/WORKFLOW.md) 中受影响的门禁。
CI 的基础边界 job 检查快照，Action job 用锁定环境重新解析，防止手改目录伪装一致。

本轮三份 YAML 的有效内容固定在 [配置兼容记录](../../integration/naming/config_compatibility.json)，
原始字节哈希仍与迁移基线核对。进食阶段和 Voice 词库按完整解析值比较；意图池只在
从原提交生成记录时去掉未使用 aliases，当前配置不再做忽略处理。其他迁移资源继续按字节比较。
后续真实功能变化需要按产品语义更新相应契约，不能用刷新命名目录绕过这些检查。
