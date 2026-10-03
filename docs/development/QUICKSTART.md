# 开发快速开始

录音试用入口：见 [WAV → ASR → Action](RECORDING_TRIAL.md)；
新增功能入口：见 [能力清单与功能草稿](FEATURE_WORKFLOW.md)。

## 选择工作范围

支持基线为 WSL2 中的 Ubuntu 22.04 / 系统 Python 3.10。源码应放 Linux 文件系统，
避免 Windows 挂载盘的执行位和构建性能差异。Git、Python 已存在时，
`python3 tools/dev.py check` 不需要 ROS、模型、原仓目录或 Python 第三方库。

只开发 Emotion/BT/Action 的普通逻辑时不必构建整机。
Voice 纯单测可独立运行；Voice 完整单测和 Vision 完整单测需要已有 ROS Humble。
安装系统 Python/ROS 属于开发机准备，仓库工具不会自动修改系统软件包。

## 准备一个模块

在新克隆的本仓根目录：

~~~bash
python3 tools/dev.py info
python3 tools/dev.py check
python3 tools/bootstrap_uv.py
python3 tools/dev.py setup behavior
python3 tools/dev.py test behavior
~~~

bootstrap 使用现有锁定 Linux x86_64 uv，下载需网络；已经有 uv 时使用
`setup behavior --uv /absolute/path/to/uv`。下载缓存可通过 UV_CACHE_DIR 复用，
缓存不是运行时源码依赖。模块解释器均位于 modules/<name>/.venv/bin/python。

| 模块 | 准备 | 日常测试 |
| --- | --- | --- |
| emotion | dev.py setup emotion | dev.py test emotion |
| behavior | dev.py setup behavior | dev.py test behavior；包含两棵既有测试目录 |
| action | dev.py setup action | dev.py test action；ROS/GUI 缺失会显式记录 skip |
| voice | dev.py setup voice | dev.py test voice；纯测试子集 |
| vision | dev.py setup vision | dev.py test vision；必须已有 Humble |

上表命令均加 `python3 tools/` 前缀。需要 Voice 完整单测：
`python3 tools/dev.py test voice --ros`。
可选真实 CPU Qwen：`python3 tools/dev.py setup voice --intent-cpu`；
每次同步都带该 extra。Emotion/BT 用于 ROS 运行时，setup 加 --ros。
模块环境彼此隔离，不在根目录 pip install 全部依赖。

test 的 JSON、JUnit、日志默认保存在 out/dev/<module>；Voice --ros 使用 voice-ros。
失败非零退出；PASS_WITH_EXPLICIT_LIMITS 表示有单独列出的跳过，不能算全部覆盖。
Voice 纯子集列出排除的文件，不冒充完整套件。Vision 的 RGA 硬件测试跳过原样保留。
JSON counts 来自 JUnit；Emotion 当前 374 entries 包含 218 tests 和 156 subtests。
不要把 subtests、重叠的 Voice pure/Humble 或契约门禁加总为独立测试数。

## 安装与跨模块验证

修改打包、资源路径或入口后，运行对应的干净 wheel 安装门禁：

~~~bash
python3 tools/check_emotion_install.py --uv /absolute/path/to/uv
python3 tools/check_behavior_install.py --uv /absolute/path/to/uv
python3 tools/check_action_install.py --uv /absolute/path/to/uv
python3 tools/check_voice_install.py --uv /absolute/path/to/uv
python3 tools/check_vision_install.py --uv /absolute/path/to/uv
~~~

只选受影响的模块。Action/BT/Needs 跨模块结果契约要求三个环境先 setup：
`python3 tools/check_contracts.py`。各阶段仍使用所属模块解释器，不合并环境。

## 启动完整本机组合

已有 ROS Humble，取得 third_party/sources.lock.json 指定的源码 bundle 后：

~~~bash
python3 tools/marsdog.py prepare --uv /absolute/path/to/uv --archive-dir /absolute/path/to/archives
python3 tools/marsdog.py build
python3 tools/marsdog.py doctor
python3 tools/marsdog.py smoke
python3 tools/marsdog.py up
~~~

源码变化后先 build，doctor 会检查安装来源和构建指纹。
使用可选 Qwen 时 prepare 也要带 --voice-intent-cpu。
工具当前固定 x86_64 开发依赖，不能据此宣称开发板已能运行。

不同隔离测试不要同时抢占同一 ROS domain。
详见 [默认组合](../LOCAL_LITE3_CPU.md)、[真实 Nav2](../LOCAL_NAV2_CPU.md)；
真实 CPU 模型是可选流程，无需权重即可完成普通开发与默认组合回归。
