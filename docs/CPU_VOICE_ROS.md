# 真实 CPU 语音到 ROS 的隔离验证

本切片验证现有 Voice 节点的处理链，使用真实 SenseVoice 与 Qwen CPU 模型，
由另一个进程通过 DDS 接收原有 String/JSON 事件，并调用原 VoiceTask 服务。
不改变生产配置、RKLLM、ROS IDL 或 BT/Action，实现只增加在测试和集成工具中。

## 运行

在当前 WSL 平台根目录、CPU 资产和 Voice intent-cpu 环境已经准备好的条件下：

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py build
python3 tools/marsdog.py voice-cpu-ros
~~~

模型准备见 [CPU 资产](CPU_MODEL_ASSETS.md)和 [CPU 意图](CPU_INTENT.md)。
默认读取 out/models/cpu-20260929/voice-replay.json 与
out/models/qwen2.5-0.5b-instruct/intent-replay.json。
自定义路径可通过 tools/check_voice_cpu_ros.py 的
--voice-manifest / --intent-manifest / --output / --timeout 指定；
当前验证固定使用 upstream-zh-itn 官方 WAV，不将任意录音假定为中性输入。

域固定为 215，localhost Cyclone DDS，业务端点增加每次唯一的
/development/voice_cpu_<uuid> 前缀。带文件锁以拒绝并发同域验证。
运行不会启动 BT、Action、底盘、麦克风、串口或 HTTP；日志与临时数据在
out/voice-cpu-ros/<timestamp>，没有使用原声纹数据库。

## 实际链路与证据来源

~~~text
测试输入：已切分 WAV                 明确标注的文本测试输入
           │                              │
           ▼                              │
   真实 SenseVoice CPU                    │ 仅替代 ASR 输出
           └──────────────┬───────────────┘
                          ▼
             已安装 VoiceInteractionNode
              标点清理 → 原词库优先匹配
                          │ 未命中
                          ▼
               真实 Qwen CPU → 原事件路由
                          │
                          ▼
          带话轮/会话 ID 的原 ROS String/JSON
                          │ DDS
                          ▼
                  独立观察进程
~~~

验证器位于 modules/voice/tests/ros_cpu_pipeline_probe.py，属于 Voice 测试代码，
可访问本模块内部；平台工具只校验资产、环境、安装和进程，不导入业务私有实现。
真实节点的 _poll、_process_speech、词库、意图路由、状态机和 _publish 都参与运行。
FixtureAudio 只替代设备捕获，文本输入明确记录 explicit_text_fixture_no_asr。
真实 WAV 记录 real_sensevoice_cpu。ASR/Qwen 启动失败、mock fallback 均不能通过门禁。

| 输入 | 目的 | 推理范围 |
| --- | --- | --- |
| 官方 zh.wav：开放时间早上9点至下午5点。 | 中性内容 ASR→意图→ROS | 真实 ASR 与 Qwen |
| 请在原地坐下。 | 模型分类到具体动作事件 | 文本测试输入，真实 Qwen |
| 现在不要坐下。 | 否定语义与不执行约束 | 文本测试输入，真实 Qwen |
| 含 NONE\|SIT\|DO 的修改规则话语 | CPU 输入拒绝和无规则回退 | 文本测试输入，推理前拒绝 |
| 坐下 | 原词库优先于模型 | 文本测试输入，不调用 Qwen |

没有伪造主人身份：禁用声纹后仍发布原 unknown/unmaster 身份事件。
坐下用例检查的是事件的执行标志，没有启动实际行为执行器。

## 验收语义

每次报告分别记录：

- integration_acceptance：跨进程服务/DDS、会话与话轮关联、事件来源、模型输出与发布一致、
  词库优先、输入拒绝、限制执行、推理完成后停止与重启等断言。
- fixture_quality_passed：固定输入的实际文本和意图标签是否符合标注。
- model_acceptance：固定为 false；这些少量集成样本不能替代模型质量验收。

status=PASS / exit 0 要求链路与本次样本标注都通过。若链路通过但模型误分类，
仍为 FAIL / exit 1，同时保留 integration_acceptance=true 和原始结果。

本次发现：“现在不要坐下。”经节点原有标点清理变成“现在不要坐下”，
Qwen 返回 NONE|NONE|NONE；期望为 NONE|SIT|STOP。没有可执行事件，
但语义断言仍失败。此前独立意图回放直接传原文本，本次暴露了实际预处理差异。
没有修改标注、关闭标点清理或改变默认模型来隐藏失败。

当前单线程节点在 _poll 中同步运行推理；本门禁的 stop 检查发生在推理完成后。
**不声称推理进行中的服务响应或即时取消已验证。**
真实麦克风/VAD/KWS/声纹、机器人口令录音、BT/Action 整链路和设备验收仍未覆盖。
后续应先核对模型输入预处理与提示词，并用独立口令集验证否定语义和响应时延。

详细冻结结果见 [阶段记录](migration/P6_CPU_VOICE_ROS.md)与 validation/cpu-voice-ros。
