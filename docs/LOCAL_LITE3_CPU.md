# Lite3 本机 CPU 统一入口

本轮验收环境：WSL Ubuntu-22.04、Python 3.10、ROS 2 Humble、x86_64。
Windows 中的代码实际位于 WSL；不要在不存在的 C:\home 路径创建第二份项目。

进入工作区：

~~~powershell
wsl.exe -d Ubuntu-22.04
~~~

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
~~~

本机依赖与安装目录已经准备好，统一启动：

~~~bash
python3 tools/marsdog.py up
~~~

Ctrl-C 关闭整个组合；也可用 --duration 20 运行一个有界会话。
任何子进程意外退出都会使整个组合退出并报告失败。工具只处理自己启动的进程组。
同一 profile 的第二个启动会被拒绝。运行日志、配置副本、SQLite 与 PID 清单在
out/local/runs/<时间>-<PID>/；最近结果在 out/local/latest-run.json。

验收与重建：

~~~bash
python3 tools/marsdog.py doctor
python3 tools/marsdog.py smoke
python3 tools/check_local_lifecycle.py
python3 tools/check_architecture.py
python3 tools/check_contracts.py
python3 tools/marsdog.py build
~~~

doctor 验证构建来源指纹、独立解释器、安装目录模块及 ROS 消息依赖；源码变化后先 build。
smoke 观察真实独立进程和 ROS 通信，关联同一个 interaction_id / goal_id 验证：
Voice mock 的 GO_HOME → BT → ExecuteBehavior → waypoint_nav → 模拟 Nav2 → Action SUCCESS。
它也检查 Vision 事件、Needs/Emotion 状态、Voice/Vision 服务与无硬件命令发布者。
go_home 按现有语义不产生 /behavior/result_event，不会伪造 Needs 结算。

初次在已有 Ubuntu 22.04 / Humble 主机准备：

~~~bash
python3 tools/marsdog.py prepare --uv /path/to/uv --archive-dir /path/to/verified-archives
python3 tools/marsdog.py build
python3 tools/marsdog.py smoke
~~~

当前机器的 uv 是 /home/elephant/MarsDog/migration/.tools/uv，归档为
/home/elephant/MarsDog/migration/archives。可设 UV_CACHE_DIR 使用已有缓存；
UV_OFFLINE=true 可验证缓存是否完整。prepare 不安装系统 ROS，不自动更新锁文件；
它分别同步五个模块和构建工具环境，校验并提取固定 ROS 依赖，恢复所需 UWB 快照。

没有模型权重、相机/麦克风或 Lite3 设备，因此当前使用：
原有 Vision/Voice mock provider、合成图像/地图、模拟 Nav2 server、模拟 Lite3 I/O。
这是软件集成环境；CPU Torch/OpenCV 可用不等于完成了真实模型推理验收。
部分原有动作会明确返回 controller_required 或 lite3_action_gated，未绕过验证门限。
profile 的确定性首个业务命令为“回家”；后续保持原有 mock 会话节奏。
真实 SLAM、NPU、音频设备、底盘、充电/电池和控制精度不在本次通过范围。

本机不加载旧机器的 ROS overlay。Cyclone 使用 loopback 和小 UDP 分片，修复当前
WSL 下已复现的 DDS 丢包；没有修改系统网络或生产 RMW 默认。固定测试 domain=210，
原生回归=211。不要同时在相同测试 domain 启动其他验收。

模块独立开发继续使用其 pyproject、uv.lock 与 tests。模块 ROS 入口、默认配置和
算法仍在原模块中；平台只生成本次运行的配置副本。跨模块协议见 interfaces/registry.json，
生产切换待办见 migration/STATUS.md 与 architecture/PLATFORM_IMPLEMENTATION_REVIEW.md。

可选的真实 Nav2 配置见 [LOCAL_NAV2_CPU.md](LOCAL_NAV2_CPU.md)。
上述默认配置与验收范围保持不变；新 profile 单独记录真实规划/控制与模拟输入的边界。
