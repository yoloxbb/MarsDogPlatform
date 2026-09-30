# ASR / Action 试用与 Vision 退出修复 — 2026-09-30

用户询问如何启动并试用 ASR 到 Action。主仓 doctor 通过后，实际运行原有
voice-cpu-ros --acceptance flow --with-behavior。

第一轮真实 ASR、Voice/BT/Action 观察均 PASS，文本“回家”完成模拟导航；
但 Vision 在 SIGTERM 后创建 wait set 时，ROS context 已失效，退出码 1，
整体必须 FAIL。原始失败报告和 Vision 堆栈保留在 before/，没有覆盖或放宽门禁。

修复仅在 Vision main 接受“context 已关闭 + failed to initialize wait set:
the given context is not valid”的 RCLError。活跃 context 的同一错误、其他 RCLError、
普通回调错误仍重新抛出；原 shutdown/destroy 流程保留。
先加八种回归，原代码 1 fail / 7 pass；修复后完整 Vision 297 pass / 3 RGA skip。
平台 79、视觉 33、任务每端 18、独立 wheel、默认 ROS 增量构建通过。
真实 CPU flow 复测 PASS，七项感知恢复 PASS；记录的所有进程退出并回收。

## 可运行命令与输入边界

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py voice-cpu-ros --acceptance flow --with-behavior
~~~

当前环境、模型和 ROS 安装已就绪。命令自动回放，约 50 秒后退出，
报告位置由最后一行 run_directory 给出。它不持续监听麦克风。

这里是分段覆盖：一条真实普通话 WAV 经过 SenseVoice/Qwen/DDS，
七条明确的文本测试输入验证控制与动作。“回家”成功来自文本注入，
不是用户录音识别出的动作指令；SIT 到 Action 后仍受未验证 Lite3 能力门限拒绝。
没有证明“对麦克风说一句回家，就完成 Action”的完整真实录音闭环。
默认 marsdog.py up 仍是 mock Voice/Vision，也不能用于宣称该闭环。

只读设备探测发现当前 WSL 缺 PortAudio 且 PATH 无 arecord；没有启动录音。
自己的 WAV、麦克风、真实唤醒及硬件动作需要另行接入。本次没有装系统音频包，
没有改模型、生产 YAML、锁文件、导航或动作执行限制。

manifest.json 记录此目录原始证据哈希，summary.json 绑定实际修改的源码哈希；
命令记录保留执行时尚未提交的状态，不能误读为已经包含在 baseline commit。
既有验收标签与旧交付包不移动；此修复作为其后的普通增量提交。
