# 本地主线软件验收基线 — 2026-09-30

本地 main 已接收五模块重构、业务恢复场景、导航交接及独立交付验收。
验收标签：acceptance/five-module-software-20260930（Git 附注标签）。
后续功能从 main 创建分支；需要固定复核基线时使用该标签。
标签解析出的 commit 是本次文档/证据收口版本，运行代码与此前实测版本相同。

## 本次操作及证据

- 初始工作区干净；原 main=3f50614，已验收分支=1835707。
- 先确认祖先关系，再 git switch main、git merge --ff-only；
  合入后 HEAD=1835707，整个 Git tree 与已验收分支完全相同，命令输出见 fast-forward.json。
- 此后只更新 README、交接、当前状态、源码交付说明、方案第 15.6 节及本目录。
  主仓与聚合目录方案同步，没有运行代码、测试、配置、依赖、IDL 或导航内部修改。
- 复核原场景证据两个 manifest 共 136 条哈希，全部一致，见 verification.json。
  先前最终交付包的独立克隆源码等价审计原样复制为 prior-package-audit.json；
  它是前一阶段的历史证据，不把其 source/ref 状态当作本次最终主线状态。
- 原 refactor/audio-contracts 分支停留在 1835707，原包及旧验证记录原样保留。
- 标签在文档/证据提交后创建；可用 git show 和 rev-parse 复核，不移动已存在标签。

## 验收范围

运行源码与 ccee303 的独立克隆实测版本一致；
1835707 只补充了该次证据和文档，本次也只调整主线说明和证据。
因此沿用 79 平台检查、声音/视觉/状态/任务/结果契约、15 包从零构建、
doctor/smoke、七项恢复场景及取消 transport 的真实结果，
详见 [前次交付验收](../scenario-delivery/DELIVERY.md)。
本次没有重复运行完整测试，也没有新增模型、真实相机、板端、实机或 hosted CI 结论。

## 复核命令

~~~bash
git show --no-patch acceptance/five-module-software-20260930
git rev-parse 'acceptance/five-module-software-20260930^{commit}'
git merge-base --is-ancestor 1835707 main
git diff --name-only 1835707 acceptance/five-module-software-20260930
~~~

最后一项应只列基线文档和本目录证据。manifest.json 记录本目录其余文件哈希。
本机 out/mainline-acceptance/final-audit.json 记录最终 commit、标签对象和干净状态；
其不进入自身指向的提交，避免自引用。

已导出的 out/handoff/source-bundle-scenarios-20260930-final 固定在 1835707，
不包含新标签或 main 的新状态。它仍可按包内 manifest 验收/克隆。
需要新主线包时从干净 main 导出新的目录；旧包不覆盖。本次没有重复生成源码包。
