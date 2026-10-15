# 事件分流与能力快照

事件的直驱和情绪影响规则仍分别由 BT 与 Emotion 持有。工具只生成查阅清单和检查引用，
不新增运行时路由服务，不改变优先级、去重、情绪数值或默认动作配置。

## 每次改规则时

在主仓执行，YAML 解析只借用已有模块的 PyYAML，不 import 该模块业务代码：

```bash
python3 -B tools/check_identifiers.py --refresh --python modules/action/.venv/bin/python
python3 -B tools/check_identifiers.py --live --python modules/action/.venv/bin/python
python3 -B tools/dev.py check
python3 -B tools/capabilities.py --output out/capabilities
```

普通 `dev.py check` 继续只依赖标准库；配置、生成器或登记代码入口变化后，旧清单会因哈希失配失败。
`--refresh` 只有所有校验通过才改写 catalog.json，不更新 compatibility_exceptions.json。
`--live` 从真实 YAML 重算并与已提交目录比较；重复键、缺模板、异常子等级等不能被刷新掩盖。

## 查看什么

| 文件 / 字段 | 内容与边界 |
| --- | --- |
| catalog.json:routes | 原有默认 YAML 路由，继续单独计数 |
| tactile_routes | 触觉 STARTED 白名单、全局 enabled、目标行为与原配置策略 |
| reaction_routes | 社交反应先选情绪表达风格、再选人物/独处上下文的备选路线，不表示同时执行 |
| emotion_effects | Emotion 的 eventRules 原规则，包括基础增量及元数据条件；不推断人格修正后的最终数值 |
| event_index | 仅直驱 / 仅影响情绪 / 双路径 / 内部触发 / 本范围未配置反应；分类不代表硬件或运行时门控已通过 |
| route_policies / category_policies | 原配置中明确给出的字段；缺省值继续由运行时代码决定 |
| runtime_entries.json | 明确评审的代码入口索引。目前登记唤醒授权后的靠近，校验代码符号及模板引用；不宣称穷举所有代码路径 |

例如摸头、摸耳、碰鼻可产生直驱候选并影响情绪；抚摸身体只有已有情绪规则。
`audio_reaction` 复用情绪模板仍归感知直驱，不能因为动作名称含 Joy 等词就归入内部触发。
情绪增量不等于立即触发行为。双路径的即时反应与后续表达仍要按场景验证；此工具不新增跨路径去重算法。

## 能力与发布记录

`tools/capabilities.py` 保留 Action 自己的配置加载和门限判断，校验子进程确实从本工作区加载报告模块。
原路由与新增触觉、社交反应、代码入口分别列出；同一行为的多种入口不是多个独立产品功能。

输出包括：

- `README.md`：事件到行为的配置状态表；`EVENT_ROUTES.md`：事件分流与情绪影响表。
- `capabilities.json`：稳定 capability_id、阶段、Unit、控制器、配置门限和三个独立验收状态。
- `capability_backlog.json`：缺模板的逐项待决策队列。owner 是角色，decision 初始为 UNDECIDED；不自动删除入口或生成占位动作。
- `release_manifest.json`：能力快照哈希、Git HEAD/dirty、配置与五模块锁文件哈希、可选验证报告引用。
- `result.json`：本次生成是否成功。生成失败会替换本目录的旧成功数据，不能继续把旧输出当作本次结果。

可附带已有 JSON 门禁报告：

```bash
python3 -B tools/capabilities.py --output out/capabilities \
  --validation-report out/identifiers/result.json
```

报告必须位于当前 checkout 内并带明确 status。记录其路径、哈希与原 status；FAIL 保持 FAIL，
引用只表示收集到这份报告，不证明它覆盖某条能力或对应当前代码。每条能力的 software、board、hardware
默认为 NOT_RECORDED；发布 acceptance 为 NOT_ASSESSED。测试报告的 PASS 不会自动升级这些状态。

`--chassis`、`--config-dir`、`--runtime-json` 继续决定被检查的组合，报告不声称该组合已经部署。
只有明确的产品决策与相应实现/验收完成后，才处理缺模板条目和既有兼容例外；历史冻结基线保持不动。

## 最小回归

平台测试覆盖双路径分类、社交反应来源、触觉缺模板、整数等级、非法情绪类型、清单漏项、
代码符号消失、禁用入口、未知能力决策、报告误绑定及失败不能保留旧 PASS。
本工具变更按 WORKFLOW 运行平台门禁、实时目录比对和能力生成；运行时规则若有变化，另外运行原模块契约和行为测试。

第六批新增 33 个表达预设及 Stage 取消入口保护。剩余 16 个能力已登记具体接入依赖；
详见 [社交表达预设与缺口处置](../../docs/development/SOCIAL_EXPRESSION_PRESETS.md)。软件计划存在不代表底盘可用或真机验收通过。
