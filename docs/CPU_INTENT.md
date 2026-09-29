# Qwen CPU 意图后端（2026-09-29）

用户明确授权暂用提供的 Qwen2.5-0.5B-Instruct，配自写提示词，并保留原 RKLLM。
已增加显式选择的 `qwen_cpu` provider；生产 YAML、RKLLM engine/provider/prompt 未改。
这是开发候选，尚未通过完整模型质量验收。默认两个本机 ROS profile 仍使用感知 mock。

## 准备与回放

在 WSL Ubuntu-22.04 的平台根目录运行：

~~~bash
cd /home/elephant/MarsDog/marsdog-platform
python3 tools/marsdog.py prepare \
  --uv /home/elephant/MarsDog/migration/.tools/uv --voice-intent-cpu
python3 tools/marsdog.py models \
  --intent-archive /home/elephant/MarsDog/Qwen2.5-0.5B-Instruct.zip
python3 tools/marsdog.py intent-replay \
  --manifest out/models/qwen2.5-0.5b-instruct/intent-replay.json
~~~

当前机器已完成准备。以后重新 prepare 时，需要保留 `--voice-intent-cpu`；
不带该参数会按默认依赖集合同步，移除 CPU 意图可选依赖。
仅同步 Voice 可使用：

~~~bash
UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv \
/home/elephant/MarsDog/migration/.tools/uv sync --project modules/voice \
  --locked --no-install-project --extra dev --extra intent-cpu --python /usr/bin/python3.10
~~~

`models` 仅验证、提取并生成清单，READY 不等于推理验收。
`intent-replay` 使用 Voice 自己的 Python 环境、真实权重、固定标注和现有事件路由；
不使用词库或规则来替代模型输出，不连接 ROS/机器人，也不发布动作。
任一分类或执行约束失败则返回 exit 1 / FAIL，并保留全部原始输出。
默认超时 600 秒；直接调用 tools/check_cpu_intent.py 可显式调整至最多 3600 秒。

## 配置与原引擎并存

开发用独立 voice 配置的对应部分如下；model 应使用模型目录的绝对路径：

~~~yaml
providers:
  intent_llm:
    enabled: true
    type: qwen_cpu
    config:
      model: /home/elephant/MarsDog/marsdog-platform/out/models/qwen2.5-0.5b-instruct
      num_threads: 2
      max_context_len: 4096
      max_new_tokens: 32
      max_input_chars: 256
~~~

这只是 provider 配置片段，不是完整启动配置。准备工具同时输出 intent-provider.json。
真实节点应通过已有 config_path 选择完整外部配置；若启用 mock.mode=event，
节点会提前使用 MockEventProvider，不会加载 Qwen。音频、唤醒、ASR 等仍需各自配置。

`type: rkllm` 和原有配置继续选原 IntentRKLLMProvider / RKLLMEngine。
CPU provider 惰性导入 Torch/Transformers，不加载 librkllmrt.so。
没有 CPU 模型或运行库时显式标为 unavailable；节点原有规则回退仍保留。
CPU 可用时主动拒绝的超长/带聊天控制符或字面协议分隔符的输入，不进入规则回退。
完整节点的标准词库匹配仍先于模型；回放特意绕过这部分，以暴露真实模型错误。

提示词在 modules/voice/marsdog_voice_interaction/adapters/llm/cpu_intent_prompt.py，
版本 qwen-cpu-intent-v2。包括三轴定义、否定/询问、主人状态、无关与转述规则、
独立示例；用户话语保持在 user message 中。生成限制为原协议合法三轴组合，
这只保证语法，不能保证语义正确。默认 greedy、CPU float32、两线程；
没有云调用、自动下载、远程模型代码或权重 pickle 加载。

结果沿用 `SOCIAL|INTENT|CONTROL`、现有事件字段和事件名；
nlu_protocol 继续为 rkllm_social_intent_control_v1，intent_source 为 qwen_cpu，
confidence=0.0（未校准，不伪造置信度）。未经路由的分类不可执行。
CPU 与 RKLLM 经过相同的文本证据、否定与动作 allowlist 门限。
没有放宽动作门限，也没有改 BT、Emotion、Action 或 ROS IDL。

## 模型与依赖来源

原 ZIP 保留，SHA256：
`e4e62c8bd6453870a6c51fafbb940cb9bff91fd785bf76c208229860f287ef2e`。
config/models/qwen2.5-0.5b-intent.lock.json 固定归档及 9 项文件的大小与哈希。
只提取模型、tokenizer、配置、README/LICENSE；不提取归档内 Git/LFS 重复对象和 hooks。

model.safetensors SHA256：
`fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`。
归档自带 main ref 为 7ae557604adf67be50417f59c2c2f167def9a775；
这里只记录用户提供的来源信息，未声称已独立验证该上游提交。
官方模型说明：https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct 。

Voice 增加 intent-cpu optional extra：Transformers 4.57.6、
Linux x86_64 的 Torch 2.13.0+cpu（官方 CPU index）；锁定于 Voice 独立 uv.lock。
原有依赖版本不升级，其他四模块环境/lock 不变。
当前验证平台为 Python 3.10 / Ubuntu 22.04 / x86_64。其他架构未验收；
ARM/RK3588 继续使用原 RKLLM 部署路径，未要求板端安装这些 CPU 依赖。
模型和约 2GB float32 工作权重不进入 Git。没有合并环境或安装系统包。

## 真实结果与限制

固定 40 条开发标注先于首轮模型运行建立，覆盖基础动作、否定、情绪、主人状态、
询问、无关、转述、注入及少量英文。不是独立测试集，也不是产品精度承诺；
第二版提示词参考了首轮错误，后续需要实际录音和独立留出集。

首轮 v1：16/40，格式与语义均有错误；发现一个字面标签注入产生可执行事件。
v2：21/40，已无该组限制执行用例的可执行事件；39 次模型输出都是合法标签，
1 条字面协议注入在模型前拒绝。拒绝不冒充预测为 NONE，原 exact-match 期望保留，
该条仍计 FAIL。残余错误含“回家/主人回来”、握手、情绪、能力/状态、玩耍等。
与原专门微调 RKLLM 的语义等价性仍为 UNKNOWN。

最终结果、完整失败列表、延时和各项软件门禁见
[本阶段记录](migration/P6_CPU_INTENT.md)与 validation/cpu-intent。
门限测试不证明所有未知输入都安全；不把此候选提升为实机默认后端。
本切片未验收 ASR→完整会话→ROS→BT 的真实模型整链路；
已有两套 profile 的回归仍使用显式 mock，不得混称为 Qwen 闭环验收。

## 节点与独立回放的输入一致性

新 CPU provider 声明 preserve_asr_text=true，节点只向它传递原始 ASR 句子，
保留标点、空格和数字表述。RKLLM、规则回退、词库和对外事件文本不变。
这是修复此前独立回放与节点删除标点后的输入差异；不为缺少标点的文本补写内容，
不改变 v2 提示词和模型标签。详见 [修复与验证](migration/P6_CPU_INPUT_TEXT.md)。
