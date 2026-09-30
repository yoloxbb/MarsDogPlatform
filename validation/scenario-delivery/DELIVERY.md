# 本轮交付验收 — 2026-09-30

本轮工程源码为 ccee3033d71cbf4de4a19199d7bcc7cab7abd1f2。
它包含已完成的五模块重构、新增恢复场景与导航交接。
源码包实际导出、逐文件校验并克隆；独立克隆状态及起始空环境检查见 clone-start.json。
所有实际命令、源码版本、工作目录、退出码和日志在 commands/。

| 检查 | 本轮实际结果 |
| --- | --- |
| 主工作区 | 79 平台测试；7 个安装后 ROS 恢复场景；初始工作区干净 |
| 保护范围 | 749 个模块/原生 ROS/生产配置/IDL/依赖/vendor/运行编排文件未变；protected-source.json |
| 独立克隆准备 | 五模块及构建工具独立环境；固定 UWB 重新物化；逐哈希校验的 deb 重新解包 |
| 克隆平台检查 | 79 通过 |
| 克隆契约 | 声音 46、视觉 33、状态 34、任务每端 18、结果 25，零跳过 |
| 克隆 ROS 构建 | 默认 15 包从零完成；build.log 含完整输出，既有编译/打包警告保留 |
| doctor | 五模块入口、公共生成类型均来自新克隆 install 与各自环境 |
| 默认整机 smoke | 十个业务/支持进程及 probe；GO_HOME 经过 BT→Action→航点→模拟 Nav2 成功 |
| 七项进程恢复 | 全通过；原有 BT client 跨 Voice/Vision 实例恢复；迟到请求不重复完成 |
| 取消 transport | 真实安装后 BT client + 测试 Action server；ACK 到终态之前保持 Goal 归属 |
| 清理 | smoke 与恢复场景所有已记录进程退出码 0，/proc 无残留，无强杀 |

只复用已有系统 Humble 和 uv/deb 下载缓存；未复制原 .venv 或 ROS build/install，
未通过原仓源码补 import。契约检查本身使用新克隆源码及各自独立环境；
doctor/smoke/recovery/transport 使用新克隆 ROS 安装，二者范围分开记录。
五模块全量单测、五个 wheel、Action 35 项回调及退出/生命周期门禁沿用未变源码的
validation/compat-refactor/r2-r4 冻结结果，没有冒充本轮重跑。

当前软件流程通过。感知是 mock，默认导航和 Lite3 I/O 为模拟；
真实相机、模型精度、板端和实机均未验收。没有远端 CI 或对外上传。
没有重新构建无改动的 SLAM/Nav2 扩展，没有改导航/避障内部或原有模型失败结论。

实际测试的源码包为 out/handoff/source-bundle-scenarios-ccee303，
其 manifest 已复制为 tested-bundle-manifest.json。
最终交付目录为 out/handoff/source-bundle-scenarios-20260930-final，
将本目录新增证据和同步文档纳入后续提交；最终 commit/文件 SHA 以包内 manifest 为准。
后续提交只允许文档与证据变化，最终包需独立 verify/clone 并比较其余源码与 ccee303
完全一致。完整步骤与包定位见 docs/deployment/SOURCE_HANDOFF.md。

manifest.json 保留第一阶段主工作区证据哈希，不改写；
delivery-manifest.json 覆盖整个本轮目录（不包含其自身）。
P7、R1/R2–R4 与更早模型/Nav2 证据全部原样保留。
