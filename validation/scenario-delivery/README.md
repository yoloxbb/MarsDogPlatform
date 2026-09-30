# 场景恢复与源码交付证据

基线 6d75931，开始时工作区干净。五模块 R1–R4 已完成，本轮不重复重构或迁移。
新增七项真实 ROS 恢复场景、八项平台门禁回归、业务验收矩阵与导航交接文档。
平台总计 79 项通过；main-recovery/result.json 中七项全部通过。
四代 Voice/Vision 进程均正常退出并回收，无强杀；BT 使用安装后的真实感知适配器。

本轮业务模块、原生导航、IDL、生产配置、锁文件、vendor 与原运行编排未变，
见 protected-source.json。原 P7、R1–R4、模型/Nav2 等冻结证据保持原样。
Voice/Vision 输入是 mock；此场景不启动完整 BT 仲裁、Action、Needs，
不代表真实相机断流、模型精度、完整动作执行或硬件验收。
完整链路及结果/取消语义对应的既有检查见 docs/development/BUSINESS_SCENARIOS.md。

commands 中保存实际命令、工作路径、基线提交、当时未提交状态、退出码和日志。
源码 commit 将包含本目录；之后独立源码包克隆的构建/启动证据追加单独目录，
不改写这里已运行的原始日志。manifest.json 列出冻结文件 SHA256。
