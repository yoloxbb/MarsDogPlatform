# CPU 感知回放：首个可验证切片

回放工具与软件回归已完成。最新 models.zip 资产接入和实际结果见
[CPU 模型实测](CPU_MODEL_ASSETS.md)：ASR 已通过，视觉仍有 2 张漏检，整体 FAIL。
validation/perception-replay/asset-audit.json 是此前缺资产阶段的冻结记录。
原有两套整机开发 profile 继续使用感知 mock。

## 范围与边界

- Vision：复用 ObjectDetectorProvider / YOLOE，在 CPU 上对带标注的单张图像做物体
  检测，检查原有归一化 bbox 和预期类别。首版需要已有的、标签已确定的 YOLOE
  .pt 或自包含 .onnx，不下载默认权重、不在线生成文本提示。
- Voice：复用 ASRSherpaProvider 的 SenseVoice / Paraformer，输入已切分的 PCM16、
  单声道、16 kHz WAV，最长 60 秒。比较预期文本，并可用原 CommandLexicon.match /
  DirectCommandMatch.to_event 检查精确词库事件。文本比较沿用原有标点/空白规范化。
- Voice 回放未验证 VAD、唤醒、KWS、声纹、RKLLM、会话状态、模糊匹配或 ROS 发布。
  catalog_event 只是现有词库构造的 payload，不能当作整条生产语音事件管线通过。
- Vision 回放未验证人脸、姿态、手势、深度融合、相机时序或 ROS 发布。
- 不启动麦克风、串口、相机、HTTP、BT、Action 或机器人。不会向硬件发命令。

两模块各有 package 内 replay 入口，保持自己的依赖/解释器。平台工具只校验资产、
启动独立进程、收集结果和超时清理。没有跨模块私有 import，也没有新增业务 common。

## 准备真实资产

以 config/replay/cpu.example.json 为模板，把副本放在自己的资产目录中，填写实际路径、
文件 SHA256 和独立标注。示例中的全零 SHA256 与路径是占位，不能用于验收。

路径相对清单文件解析，也可以是绝对路径；不会相对进程工作目录猜测。
每项模型、tokens、图像和 WAV 都要有 SHA256。原语音词库默认取维护中的
modules/voice/config/command_catalog.yaml，工具记录其哈希；也可明确提供另一个已标注
catalog 资产。可以只保留 vision 或 voice 一节，分别推进两个模块。

获取哈希：

~~~bash
sha256sum /absolute/path/to/model.onnx /absolute/path/to/tokens.txt
~~~

视觉样本选择 expected_labels 非空列表，或 expected_empty=true（二者互斥）。
预期类别必须来自实际模型的标签；空检测不会让正例通过。语音样本必须有
expected_text，可加 expected_event_type，例如 EVT_VOICE_COMMAND_GO_HOME。
不要根据识别结果反过来填写答案以制造通过。

本轮不转换 RKNN/RKLLM 文件，不替换为随机公开模型。模型外部数据文件、多文件
导出目录、动态文本编码器等资产组合尚不在首版覆盖范围；单文件哈希不证明这些
未声明的依赖也已被固定。模型版本/标签来源应在清单 description 中说明。

## 统一命令

在 WSL 主仓中：

~~~bash
python3 tools/marsdog.py replay --manifest /absolute/path/to/cpu-replay.json --check-only
python3 tools/marsdog.py replay --manifest /absolute/path/to/cpu-replay.json
~~~

可用 --output 指定证据根目录。每次运行创建独立子目录，保留 preflight、模块请求、
日志和 JSON 报告；失败时同样保留。不会覆盖既有运行结果。

直接使用工具可设置每模块超时（默认 300 秒）：

~~~bash
python3 tools/check_perception_replay.py --manifest /absolute/path/to/cpu-replay.json --timeout 600
~~~

| 状态 | 退出码 | 含义 |
| --- | --- | --- |
| READY | 0 | 仅 --check-only 的资产校验通过，未运行模型 |
| PASS | 0 | 所选模块的全部标注样本推理与检查通过 |
| BLOCKED_MISSING_ASSETS | 2 | 有资产不存在，没有开始模型验收 |
| FAIL | 1 | 清单/哈希/格式/依赖/推理/断言/子进程失败 |

model_acceptance 只有实际 PASS 才为 true。哈希正确不代表模型能加载或精度合格。
回放显式 device/provider=cpu，禁用 Ultralytics 自动安装与在线检查；保持既有 lock。
如果已锁定环境缺少某个导出格式的运行依赖，记录失败后再按实际模型做独立依赖变更，
不能让工具在验收途中自动安装或升级包。

## 实现例外与兼容性

ObjectDetectorProvider 仅增加可选 device 参数透传；ASRSherpaProvider 仅增加可选
provider 参数透传。不配置时保持原调用参数、生产 YAML、ROS IDL 和业务算法。
Voice 生产节点原有的 ASR 失败回退 mock 行为仍保留；回放直接使用真实 ASR provider，
初始化失败立即拒绝验收，没有修改该生产语义。

工具通过显式源包路径运行开发代码，各模块仍用自己的 .venv。独立 wheel 的安装门禁
另外验证 replay 模块字节及 python -m ...replay --help，证明入口也被正确打包；
正式 ROS 安装通过正常 build 更新，未混合环境。

## 当前证据和后续

新增测试使用明确的模型替身验证适配器行为，不能当作实际模型识别通过。
本轮 Vision 289 passed / 3 RGA skipped；Voice 380 passed；平台工具 19 项（含此前
6 项构建隔离测试）；原有契约 25 项通过。wheel、ROS 构建及新旧 profile smoke 通过。
证据见 validation/perception-replay；旧的冻结 Nav2/本机集成证据保持原样。

现可用统一 models 命令准备已固定资产并运行本工具。下一步补充机器人实际录音/图像，
并处理当前视觉漏检及 RKLLM 原权重缺失。
首批样本通过后再把真实输入接入隔离 ROS 事件和服务验收，不跳过模型层直接宣称整机成功。

SIGINT/SIGTERM 中断与超时会回收本次模型子进程并保存 FAIL，不能留下 READY
冒充已完成。平台测试包含实际阻塞子进程的中断验证；该进程不运行模型。

模型接入后新增修复：一个模块验收失败仍保留其真实推理报告，并继续运行其他独立模块。
整体仍返回 FAIL；inference_executed 与 model_acceptance 分别表达是否执行和是否通过，
不把已运行但断言失败误写成没有运行。
