# 能力清单与功能草稿

先用原配置生成能力清单，再决定修改哪个模块。工具不会创建新的运行时总控或业务 common。

## 查看能力

~~~bash
python3 -B tools/marsdog.py capabilities
~~~

输出 `out/capabilities/README.md` 和 `capabilities.json`。
清单关联词库命令、声明式事件路由、BT 候选和 Action 模板；
Action 在自己的独立 Python 环境内读取 ConfigLoader 和 Lite3 原策略，工具只汇总 JSON。

默认检查源配置。实际部署会覆盖 enabled 等参数，因此也可指定配置目录和明确布尔覆盖：

~~~bash
python3 -B tools/marsdog.py capabilities \
  --config-dir modules/action/config \
  --runtime-json docs/development/local-capability-overrides.json \
  --output out/capabilities-local
~~~

示例覆盖与本机模拟组合的主要授权参数一致，但清单不是正在运行的 ROS 图快照；
不会查询传感器、姿态或适配器就绪状态。配置哈希、覆盖值和模块来源均保留在 JSON。
`declared_verified` 是既有配置元数据；本次 `hardware_acceptance` 始终为 unknown。

| 状态 | 意义 |
| --- | --- |
| missing_template | 声明的路由引用了尚未提供的 Action 模板 |
| blocked | 当前配置/策略阻断了路由或必选阶段的所有候选 |
| runtime_check_required | 配置检查不能决定执行结果，仍需授权、目标、姿态及设备证据 |
| simulated_only | Unit 路由为 mock，不能代表硬件支持 |

JSON 还列出每个阶段是否必选、候选 Unit、部分/全部候选是否被门限阻断。
125 条声明式路由中，既有 49 条引用缺失模板；本轮只使缺口可见，没有补造动作。
代码专用会话路径不在该声明式路由计数内。详细命名规则见
[标识目录](../../interfaces/naming/README.md)。

## 新功能起点

下面只生成一个复用现有 `sit_down` 模板的开发示例，并不启用新口令：

~~~bash
python3 -B tools/marsdog.py new-feature welcome_demo \
  --phrase 测试欢迎 --behavior sit_down
python3 -B tools/marsdog.py new-feature \
  --check out/feature-drafts/welcome_demo/feature.json
~~~

已有目录拒绝覆盖；事件、command_id、intent 冲突或不存在的模板会被拒绝。
草稿包含名称与短语、带目标位置的配置片段、Voice/BT/Action 契约测试，
以及正向、否定、错误命令身份、去重、执行中取消和能力拒绝的验收清单。
`VALID_DRAFT_NOT_ACTIVATED` 只表示草稿静态校验通过，验收清单仍为 NOT_RUN。

生成内容不是可直接覆盖整份 YAML 的文件。开发者应分别修改：

1. Voice 的词库、事件声明及 command_key → NLU 协议映射，维护词库来源和版本；
   不靠生成器推断新模型语义。
2. Behavior 的 audio_direct 事件映射和 intent_action_pool，检查行为规格、目标、
   优先级、TTL、超时、中断及会话生命周期。
3. Action 的真实能力实现与已有门限。草稿只复用现有模板；
   新 Unit/设备协议必须先在 owning module 明确实现和验证。
4. 只有产品语义需要时才修改 Emotion/Needs 结算；不自动增加结算或伪造证据。

分别进入 modules/voice、modules/behavior、modules/action，
用其 `.venv/bin/python -B -m pytest /absolute/path/to/draft/test_<module>_contract.py`
运行对应模板测试。未实现前 Voice/BT 正向测试应失败；Action 模板引用测试可以通过，
但不能替代去重、取消和设备拒绝场景。

实现后按 [开发流程](WORKFLOW.md) 运行门禁，更新命名目录并检查新缺口，
再运行 [录音试用](RECORDING_TRIAL.md)。历史冻结契约不能通过刷新基线掩盖差异。

## 仲裁场景回归

~~~bash
python3 -B tools/marsdog.py build
python3 -B tools/check_decision_scenarios.py
~~~

独占 localhost domain 217，运行安装后的完整 BT 和 Action；
输入明确的协议/状态/视觉样例，Lite3/Nav2 使用模拟。覆盖：

- 同一事件重复投递，只下发一个 Goal；
- 连续同级命令等待前一终态；
- STOP 抢占运行中的命令，旧 Goal 先取消并产生终态，再下发替代 Goal；
- 视觉目标过期时，在动作下发前拒绝需要该目标的命令；
- 命令完成后，Needs 候选先于 Emotion 候选被选择。

每个已下发 Goal 都必须恰好一个终态，四个组件正常退出，无硬件 Topic 发布者。
这是 BT/Action 决策验证，不是 ASR、真实视觉断流或模型质量测试。
移动中的目标丢失由既有 Action 单测另行覆盖；感知任务恢复见
[业务矩阵](BUSINESS_SCENARIOS.md)。新增门禁已接入手动 Humble CI job；
本地通过不代表远端 CI 已运行。
