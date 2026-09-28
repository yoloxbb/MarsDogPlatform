# MarsDog 平台整合：新会话交接与下一步执行计划

更新时间：2026-09-29（Asia/Shanghai）
工作区：`/home/elephant/MarsDog`
平台仓库：`/home/elephant/MarsDog/marsdog-platform`

## 1. 总体目标

把当前多个独立仓库逐步迁移为一个可长期维护的软件平台，同时保持现有行为、ROS 接口、配置语义和 Git 历史。迁移必须渐进、可验证、可回退：先建立边界和测试，再移动实现；不能为了目录统一重写稳定算法。

不在本阶段实现运动控制算法或嵌入式内部逻辑。只保留未来稳定的外部能力边界。不得臆测缺失硬件、NPU、底盘或电池生产实现。

最终平台需要支持：

- Vision、Voice、Emotion/Needs、BehaviorTree、Action、SLAM/Nav 独立开发和测试；
- 完整机器人系统的集成启动和接口验证；
- 每个 Python 模块保留独立环境，避免把不兼容的推理依赖强行合并；
- ROS package、topic、service、action、配置和第三方源码有清晰所有权；
- 新的跨模块功能通过公共接口协作，不直接 import 其他模块私有实现；
- 保留原仓库和可验证的历史来源。

## 2. 当前平台基线

平台仓库当前分支为 `main`，最新检查点：

```text
9fb5142 feat(platform): verify navigation recovery and require battery evidence
```

该仓库没有 remote，也没有执行 push、PR 或 hosted CI。原始七个 Git 仓库保持不变，当前来源快照和原始 HEAD 在 `integration/migration/baseline/sources.json` 及迁移工作区中记录。

平台内已经完成并验证历史导入的模块：

- `modules/emotion`：MarsDogEmotion，19 个可达提交，已保留 commit map 和 all-refs bundle；
- `modules/behavior`：20260702_MarsDogTree，7 个提交；
- `modules/action`：20260707_MarsDogAction，5 个提交。

平台内已经复制但尚未宣称生产部署的新增源码：

- `interfaces/ros2/marsdog_interfaces`：用户新增接口包；
- `robotics/ros2/src/waypoint_nav`：用户新增 waypoint 导航包。

原始来源仍位于：

- `MarsDog`：Vision；
- `MarsDogVoiceInteraction`：Voice；
- `MarsDogEmotion`；
- `20260702_MarsDogTree`；
- `20260707_MarsDogAction`；
- `slam/robot_ws`：robot_ws；
- `slam/rtabmap_ws`：rtabmap_ws。

## 3. 已完成的架构与验证工作

### 3.1 Emotion / Needs

- 保留原 `marsdog_core`、`marsdog_ros2` 和 ROS package。
- 没有把业务规则塞进 common。
- 已验证纯测试、clean wheel、隔离安装后的真实 Needs ROS 端点。
- 已覆盖电量证据规则：只有新鲜、有限、非模拟的 observation 可以补充 Energy；legacy scalar 不再补充；无证据、过期、无效、simulated 电量都不能补充。
- 证据契约：`interfaces/application/BATTERY_OBSERVATION.md`。

### 3.2 BehaviorTree / Action

- BehaviorTree 负责决策、候选行为、优先级、仲裁、抢占和结果映射。
- Action 负责高层技能编排、动作生命周期、导航/动作能力调用和对外 action/service 适配；它不是底层运动控制算法。
- Action 与 BT 均不直接实现未来运动控制或嵌入式算法。
- 已验证导航恢复策略：自动 cancel 不等于操作者确认的 recovery release；`release_recovery` 需要明确的 operator confirmation 和 stopped 条件。
- `go_home` 使用现有到达后的 hold-position 完成语义；没有新增底层运动序列。
- 已验证 Action、BT、Needs 跨进程电量结果契约。
- 导航 supplemental gate：31 tests + 2 subtests；public Action transport probe 通过。
- Action 纯测试：420 passed / 29 skipped；跳过项是硬件/生产 ROS 环境，不得算成通过。
- Behavior 当前完整验证记录保留在 `docs/migration/P3_BEHAVIOR.md` 及 `validation`。

### 3.3 ROS / Navigation

- `robot_ws` 和 `rtabmap_ws` 原仓库未改动。
- `waypoint_nav` 目前是用户新放入的独立源码，已复制到平台 `robotics/ros2/src/waypoint_nav`，没有宣称它已经和真实 robot_ws/rtabmap_ws 完整部署接通。
- ROS 相关验证在 ROS 2 Humble 隔离环境，使用 localhost test domain 和 fake Nav2，不连接生产机器人。
- 已知默认 Fast DDS 发现问题：测试使用本地 loopback/UDP 隔离配置；生产默认 discovery 仍需部署环境确认，不能在没有证据时修改。
- rtabmap 第三方源码与自研代码仍需后续单独 inventory；不得把第三方代码直接当 MarsDog 自研代码。

## 4. Voice 当前进度

Voice 尚未导入平台，原始源快照为：

```text
/home/elephant/MarsDog/migration/work/p1-20260928/sources/voice
```

原 Voice 约束：

- Python `>=3.10,<3.11`；ROS 2 Humble；
- ROS package：`marsdog_voice_interaction`；
- 自定义 service：`marsdog_voice_interaction/srv/VoiceTask.srv`；
- 发布 `/perception/audio_event`，类型 `std_msgs/msg/String`；
- 发布 `/perception/voice/enrollment_event`，类型 `std_msgs/msg/String`；
- 提供 `/perception/voice/task`，类型 `marsdog_voice_interaction/srv/VoiceTask`；
- 入口：`marsdog_voice_interaction.main:main`，console script `marsdog-voice-interaction`；
- 启动：`launch/voice.launch.py`；构建：ROS Humble `colcon build --packages-select marsdog_voice_interaction`；
- 不订阅 Vision，不直接控制底盘，不负责行为优先级、排队或抢占；事件由 BehaviorTree 等下游消费。

Voice 原锁定依赖现已成功恢复到其隔离快照环境（命令结束码 0）：

```text
cd /home/elephant/MarsDog/home/elephant/MarsDog/migration/work/p1-20260928/sources/voice
UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv \
/home/elephant/MarsDog/migration/.tools/uv sync --locked --no-install-project --extra dev \
  --python /usr/bin/python3.10
```

已确认安装的关键包：

- `numpy==1.26.4`
- `scipy==1.15.3`
- `sherpa-onnx==1.13.3`
- `sherpa-onnx-core==1.13.3`
- `fastapi==0.141.1`
- `httpx==0.28.1`
- `pydantic==2.13.4`
- `sounddevice==0.5.5`
- `pytest==8.4.2`

这只是依赖恢复，不是测试通过，也不是模型/硬件验收。下一步必须运行原 Voice 测试。

Voice 原配置中的重要外部运行时：

- 配置文件：`config/voice.yaml`；
- 模型路径默认从 YAML 文件目录相对解析到项目同级 `../models`；
- `lib/librkllmrt.so` 是 ARM64/aarch64 RKLLM 运行库，不能在当前 x86 主机执行；
- 模型文件没有随源码快照提供，不能伪造、移动或改写成测试模型；
- `storage.root` 下的声纹注册表、WAV 和 embedding 属于运行期生物特征数据，不应提交；
- `utils/ros_entrypoint.py` 支持 `MARSDOG_PYTHON`、`VIRTUAL_ENV` 和 `.venv/bin/python` 搜索，迁移时要保留其行为。

Voice 原仓存在 `setup.py`、`pyproject.toml`、`CMakeLists.txt`，package data 需要在 clean wheel 和 ROS 安装两条路径分别验证。不要在未测试前修改 packaging。

## 5. 当前待执行的第一件事

在不修改原始 Voice 源码的前提下，运行其原仓测试：

```bash
cd /home/elephant/MarsDog/home/elephant/MarsDog/migration/work/p1-20260928/sources/voice
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -B -m pytest tests -q -p no:cacheprovider \
  --junitxml=/home/elephant/MarsDog/migration/reports/p1-20260928/p4-voice-junit.xml
```

记录 stdout/stderr 到：

```text
/home/elephant/MarsDog/migration/reports/p1-20260928/p4-voice-tests.log
```

若测试失败：

1. 先判断是源码失败、测试假设、缺少模型/硬件、还是环境问题；
2. 不能为了迁移而放宽依赖、改测试或修改原仓；
3. 对纯测试中的真实缺陷，先记录并暂停导入；
4. 对明确硬件/模型边界的 skip，单独记录，不能把 skip 算 pass。

若原测试通过，继续做 Voice 模块 gate：

- 检查测试数量和 skip/failure；
- 检查纯 Python import，不加载 ROS node 和 ARM RKLLM；
- 检查配置路径解析保持 YAML-relative 语义；
- 检查无 Vision/Action/BT 私有 import；
- 检查 source tree、config、launch、service、static asset 和 `lib` 的清单及 hash；
- 构建 clean wheel，安装到独立 Python 3.10 环境，验证 console script 和静态资源；
- 使用 ROS Humble 隔离 build 验证 package/service 生成，禁止连接生产 ROS domain。

## 6. Voice 导入规则

只有 Voice gate 明确通过后，才能扩展 `integration/migration/tools/import_verified_history.py` 的 module choices 增加 `voice`，然后使用该工具导入历史。

导入必须：

- 只操作 `/home/elephant/MarsDog/migration/work/history-voice` 的 disposable clone；
- 生成并验证 all-refs bundle、fsck、ref 列表、commit count 和 commit map；
- 使用 `git-filter-repo --to-subdirectory-filter modules/voice`；
- 比较原快照与 `modules/voice` 下文件内容和 mode；
- 原始 Voice 仓库 HEAD、索引、工作树和文件 hash 必须保持不变；
- 导入后创建 `docs/migration/history/voice-import.json` 和 `voice-commit-map.txt`；
- 使用明确的本地 migration commit；
- 不删除原仓库，不改变原 ROS package 名称和 topic/service/action 名称。

工具当前只允许 `behavior`、`action`，尚未加入 `voice`。不要在 gate 前直接改工具或目标仓。

## 7. 之后的迁移顺序

1. **Voice**：锁环境、原测试、clean wheel、ROS package build、历史导入。
2. **Vision**：单独恢复原锁定环境。它有 Torch/Ultralytics/OpenCV 等大依赖，不能拿 Voice 或平台环境代替。先做依赖可得性和纯测试 gate。
3. **robot_ws / waypoint_nav**：保持 ROS workspace 边界；建立 package inventory、launch/profile 和 fake transport 验证；不重写 SLAM/Nav。
4. **rtabmap_ws**：把第三方 RTAB-Map 与 MarsDog 自研修改明确分开，记录版本/patch/provenance，再决定是否纳入平台源码树。
5. **统一集成启动和 CI**：先有各模块独立 gate，再加集成入口。禁止用一个 root lockfile 强制合并 Torch、ROS、sherpa、RKLLM 等不兼容环境。
6. **硬件/生产验收**：模型、NPU、音频、摄像头、真实导航、电池、底盘和嵌入式协议都需要真实部署事实；当前不能宣称完成。

## 8. Python 环境与依赖原则

当前选择是“平台单仓 + 模块独立 lock/env”，而不是单一 Python lockfile：

- Voice/Emotion/Behavior/Action 各自保留 `pyproject.toml` 和 `uv.lock`；
- ROS Humble build tools 单独环境；
- Vision 的 Torch/OpenCV/CUDA/NPU 依赖单独管理；
- 共享接口只放 schema/IDL/轻量 contract，不把业务实现放进 common；
- 发现冲突时记录矩阵，不直接升级或降级锁定版本。

重点版本冲突风险：

- Vision 需要 Torch 2.13.0 / Ultralytics / OpenCV 组合；
- Voice 使用 NumPy `<2`，Action 当前锁定 NumPy 2.2.6；
- Voice 使用 pydantic 2.x 通过 FastAPI，其他模块不能假设同一 pydantic 版本；
- ROS Python 包由系统 Humble 提供，不能用 pip 环境覆盖；
- sherpa-onnx/RKLLM 模型运行时与 x86 主机、ARM 板端不同。

## 9. 不可违反的工作规则

- 阅读 `AGENTS.md`、README 和相关 migration 文档后再改代码；
- 原始仓库只能读，除非人明确批准；
- 不执行 git checkout/reset/rebase/commit 于原仓库；
- 不修改 requirements、pyproject、CMakeLists、package.xml 来绕过 gate；
- 不安装系统依赖，不伪造模型，不启动生产硬件；
- 不把 skip 当 pass；
- 不直接 import 其他模块私有实现；
- 不创建运动控制或嵌入式实现；
- 不删除无法恢复的数据、历史或生产代码；
- 平台迁移是可回退的，目标仓每个阶段都必须保持清洁检查点。

## 10. 新会话起始命令

```bash
# WSL 路径
cd /home/elephant/MarsDog/marsdog-platform

# 核对平台和原仓不变
python3 -B integration/migration/tools/check_baseline.py

git status --short

# 使用 retained migration workspace 和已恢复缓存
export MARSDOG_MIGRATION_WORKSPACE=/home/elephant/MarsDog/migration
export MARSDOG_LEGACY_ROOT=/home/elephant/MarsDog
export UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv

# Voice 原测试（首个实际动作）
cd /home/elephant/MarsDog/home/elephant/MarsDog/migration/work/p1-20260928/sources/voice
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -B -m pytest tests -q -p no:cacheprovider \
  --junitxml=/home/elephant/MarsDog/migration/reports/p1-20260928/p4-voice-junit.xml \
  2>&1 | tee /home/elephant/MarsDog/migration/reports/p1-20260928/p4-voice-tests.log
```

注意：如果从 Windows PowerShell 调用 WSL，PowerShell here-string 末尾会附带 CR；bash 脚本末尾加单独的 `# end`，避免最后一个路径或命令带 `\r`。

## 11. 交接完成状态

本文档用于新会话接续，不能代替测试结果。新会话必须先执行第 5 节原 Voice 测试，并在测试完成后更新本文件、`docs/migration/STATUS.md` 和相应 validation 报告，然后再做导入决定。
