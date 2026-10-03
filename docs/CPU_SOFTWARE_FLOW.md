# CPU 软件流程验收

需要试自己的录音时，使用新增 [trial 入口及关联诊断](development/RECORDING_TRIAL.md)。
下面的固定 voice-cpu-ros 回归入口继续保留。

当前优先级由用户明确为：先保证流程，模型精度暂不阻塞集成。保留原误分类证据，
不继续调提示词或改标注。以下入口只对本机软件流程负责，不代表实机验收。

## 运行已有 ASR 与动作分段回放

当前 WSL Ubuntu-22.04 中，模型和环境已准备好。此命令自动回放并退出，
不监听麦克风：真实 WAV 是普通语句，动作命令另用文本注入。
因此它验证 ASR 与后续动作链路的分段覆盖，尚不能证明用户录音口令直接到 Action。

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py doctor
# 仅 doctor 报告安装陈旧时，先运行 python3 tools/marsdog.py build
python3 tools/marsdog.py voice-cpu-ros --acceptance flow --with-behavior
~~~

输出在 out/voice-cpu-ros/<timestamp>/result.json。工具启动并收回本轮拥有的进程，
验证完成自动退出。不会修改默认 lite3-local-cpu / lite3-nav2-cpu 启动配置。
仅验证 Voice 可去掉 --with-behavior；默认 --acceptance strict 仍要求固定样本标签匹配。
flow 模式保留 fixture_quality_passed 和原始错误，但不因标签误分类单独失败。
接口、事件来源、会话归属、停止、异常退出或执行限制失败，flow 模式仍失败。

首次准备环境、模型及 CPU 可选依赖见 [CPU 意图后端](CPU_INTENT.md)。
不要直接把原模型 ZIP、Git/hooks 或虚拟环境提交到源码仓库。

## 实际链路

~~~text
官方 WAV → 真实 SenseVoice CPU ──┐
明确标注的文本测试输入 ──────────┤
                                ▼
                      已安装 Voice 节点
                    原词库 / Qwen CPU / 事件门限
                                │ 原 ROS String/JSON
                                ▼
                       BT → ExecuteBehavior → Action
                                                  │
                                      航点服务 → 模拟 Nav2
                                                  │
                                       原执行终态回到 BT
~~~

并行运行原 Emotion/Needs、时间/性格和 mock Vision。各 Python 模块仍在自己的环境，
没有跨模块私有 import。正式 Qwen v2、原 RKLLM、五套依赖锁和公开 ROS IDL 保持不变。
本机域 215、localhost DDS；Voice 端点带唯一前缀，其他节点通过标准 ROS remap 连接。

验证覆盖：

- 一条官方 WAV 经真实 ASR、Qwen 和 DDS；命令是明确的文本输入，不冒充录音。
- 原五个 Voice 场景及 start/hold/release/get-state/stop。
- 真实 Qwen 正在计算时查询、停止和重启，服务必须在 2 秒内返回。
- 停止响应必须早于该次真实推理结束；旧话轮不能发布迟到语义事件。
- 新会话能继续词库命令；停止状态不处理新增捕获输入。
- Qwen 产生的可执行事件必须对应唯一 BT/Action Goal 和唯一终态。
- 已有 Lite3 未验证能力拒绝允许作为明确失败终态返回；被验收命令的未知执行失败不能冒充通过。
- 词库“回家”必须完成 Action/航点/模拟导航 SUCCESS。
- Emotion/Needs 状态与模拟执行证据可观察，所有配套进程正常退出。
- 不存在 /simple_cmd、/cmd_vel、/api/sport/request、/robot_status 硬件话题发布者。

本轮实际 Qwen SIT → BT sit_down → Action 返回原能力门限拒绝：
lite3_action_gated:unit_id=ACT_BASIC_SIT,fidelity=proxy,verified=False。
这是拒绝流程通过，不能写成机器人已坐下；没有放开 allow_unverified 来制造动作成功。
导航成功来自“回家”词库命令，不能写成 Qwen 正确识别了导航指令。

## CPU 推理与会话控制

此前同步 Qwen 占据 ROS 回调约 7 秒，状态查询也会阻塞。现在仅显式 CPU provider
声明 background_intent：模型计算移到一个后台任务；路由、状态修改和事件发布
仍在 ROS 线程。完成时核对原 interaction_id / wake_id；停止、超时或新唤醒会使
旧结果失效。后台异常走原未知事件路径，恢复采集，不产生伪造模型输出。

一个时刻只允许一个模型任务，旧任务未结束时不排队新的推理/采集。stop_listening
立即结束会话；新会话可立即建立，但采集等待旧计算退出后恢复。没有强杀 Torch 算子，
也不宣称 CPU 计算立即停止。销毁节点时使用原 provider.stop 释放模型并回收后台线程。

原 RKLLM、规则、词库和 ASR/声纹处理仍沿用原路径。此检查证明当前 Qwen 推理中的
服务响应，不能推断所有设备驱动、ASR/声纹调用或任意故障都具备实时响应。

## 当前边界与证据

430 项 Voice 单元测试、39 项平台测试及 25 项契约分别记录；单元测试不等于真实 ROS。
真实 CPU 流程、软件门禁、原阻塞复现和验证器审计同步修复证据冻结在 validation/cpu-flow。
model_acceptance 和 hardware_acceptance 保持 false，不影响本阶段软件流程判断。

导航、相机、Lite3 I/O 是显式模拟；真实麦克风/VAD/KWS、SLAM 传感器和 Lite3 设备
仍需后续环境。默认整机启动仍可使用 python3 tools/marsdog.py up。
后续继续扩大可复用的模块流程和故障恢复验证，精度优化暂缓。

## 2026-09-30 试用复核

当前主线试跑发现 Vision 在退出时遇到 context 已关闭的 wait-set 竞态：
业务观察通过，但组件非零退出使整轮 FAIL。已加精确异常处理和八种回归，
不吞掉活跃 context 或其他回调故障；重建后 CPU flow、感知恢复均 PASS。
完整失败/成功证据见 [试用记录](../validation/voice-action-trial/README.md)。

当前 WSL 的 sounddevice 导入报告 PortAudio library not found，PATH 也无 arecord。
默认 up 使用 mock；已有声纹上传网页用于注册，不是语音动作入口。
麦克风或用户 WAV 口令需独立接入，不把现有固定文本回放当作真实语音指令验收。
