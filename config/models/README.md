# 模型目录与部署约定

统一的默认模型根目录是 **MarsDogPlatform 仓库根目录下的 models/**。
当前工作区对应 /home/elephant/MarsDog/marsdog-platform/models。
config/models 只保存版本、来源、SHA256 等清单；模型权重单独分发。
models 下除 README.md 外均由根 .gitignore 忽略，wheel 和源码交付不包含权重。

~~~text
MarsDogPlatform/
├── models/                         # 运行时资产，默认不提交
│   ├── vad/
│   ├── wakeup/
│   ├── asr/
│   ├── speaker/
│   ├── llm/
│   │   └── qwen2.5-0.5b-instruct/   # 可选 CPU 意图目录
│   ├── vision/
│   └── cpu-20260929/                # 固定 CPU 回放资产包及其清单
├── config/models/                  # 提交到 Git 的版本与校验清单
├── modules/
└── tools/
~~~

目录名和模型文件名仍以 Voice/Vision 生产 YAML 为准。本次只统一路径，不替换
RKNN/RKLLM/ONNX 权重、backend、阈值或精度。cpu-20260929 是独立的已锁定回放包，
内部保留 archive/models、downloads、派生模型、准备依赖和 receipts 的既有布局；
不能把它当成生产 YAML 所要求的完整目录。

## 路径解析

- Voice 默认 YAML 使用 ${MARSDOG_MODEL_DIR}/asr/... 等路径。
- Vision 默认 YAML 使用 ${MARSDOG_VISION_MODEL_DIR}/...，该变量默认等于模型根目录下的 vision。
- MARSDOG_MODEL_DIR 未设置时，从配置位置、再从已加载的模块位置向上查找
  platform/modules.json，以其所在仓库的 models 为根。不依赖启动时的工作目录，
  也不因其他目录中恰好存在权重而切换模型。
- MARSDOG_MODEL_DIR 可设为其他绝对目录；Vision 原有的 MARSDOG_VISION_MODEL_DIR
  可单独覆盖视觉目录，优先于统一根目录。路径允许 ~，环境变量不可使用相对路径。
- 单独部署 wheel/ROS 安装产物到仓库外时，使用模型变量的配置需显式设置根目录。
  无法定位根目录会明确报错。显式绝对模型路径和不引用模型变量的 mock 配置不受影响。
- 自定义 Voice YAML 中原有相对路径仍相对于该 YAML；词库、关键词文件、SDK lib_path、
  storage.root 和日志路径继续沿用原规则。Vision 的项目/数据变量语义保持原样。

板端或多项目共用资产示例：

~~~bash
export MARSDOG_MODEL_DIR=/srv/marsdog/models
# 仅在视觉资产单独存放时设置：
export MARSDOG_VISION_MODEL_DIR=/srv/marsdog/vision-models
~~~

将变量传给启动进程即可，ROS launch 子进程会继承。无需修改默认 YAML，
也不需要模型目录存在于 Python 包或 ROS share 内。

## 准备与现有 CPU 资产

新准备命令默认写入模型根目录：

~~~bash
python3 tools/marsdog.py models --model-archive /absolute/path/models.zip --download
python3 tools/marsdog.py models --intent-archive /absolute/path/Qwen2.5-0.5B-Instruct.zip
~~~

前者写入 models/cpu-20260929，后者写入 models/llm/qwen2.5-0.5b-instruct；
设置 MARSDOG_MODEL_DIR 后使用外部根目录。--output 可指定完整输出目录。
清单校验和拒绝覆盖不匹配资产的规则保持不变。

本机以前准备的 out/models/cpu-20260929 和 out/models/qwen2.5-0.5b-instruct
保留原位置及内容，没有重复提取、下载、转换模型，也没有改写历史验收记录。
trial 和 voice-cpu-ros 默认优先使用新目录；仅在未设置 MARSDOG_MODEL_DIR、
且对应新资产包目录尚不存在时，兼容读取旧清单并输出提示。
新包不完整或显式外部根目录缺文件时会失败，不会悄悄使用另一份模型。

也可始终显式选择旧清单：

~~~bash
python3 tools/recording_trial.py --wav /absolute/path/command.wav \
  --voice-manifest out/models/cpu-20260929/voice-replay.json \
  --intent-manifest out/models/qwen2.5-0.5b-instruct/intent-replay.json
~~~

已有清单和派生记录含绝对路径，不能只移动文件夹就假定可用。后续迁移实际权重时，
应在新位置通过准备工具生成并核验清单，再验证消费者；确认前保留旧目录。
清理 out 时仍需保留当前正在使用的旧资产。

构建、默认 mock 启动不要求模型存在。真实模型试用见
[CPU 资产](../../docs/CPU_MODEL_ASSETS.md)、
[CPU 意图](../../docs/CPU_INTENT.md)和
[录音到动作](../../docs/development/RECORDING_TRIAL.md)。
