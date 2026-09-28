# P4a — Voice 软件迁移（2026-09-29）

状态：软件迁移通过，生产部署与模型/硬件验收未完成。

## 迁移结果和来源

Voice 已从 MarsDogVoiceInteraction 导入 modules/voice。原 HEAD 为
df85e30509b9561d782c1963e3ff362d39cbfa14；仅在可丢弃副本中添加 modules/voice
路径前缀。95 个跟踪文件的内容、mode、路径集合均与冻结基线一致，未改业务源码、
pyproject、uv.lock、ROS manifest、CMake、IDL、默认配置或静态资源。

23 个可达提交、所有原 refs 已存入可恢复 bundle，恢复后 refs/fsck/commit count
核对通过。主线导入 commit 为 0384a81；其他历史 refs 保留在 bundle 中，不能把
“归档所有 refs”误称为“平台 main 包含每一个旁支提交”。原到新 SHA 映射以及
archive hash 在 docs/migration/history/voice-import.json 和 voice-commit-map.txt。
原七个仓库继续通过原始基线核对。

## 边界

- Voice 负责识别链路、会话、声纹管理和语音事件，不直接调用 BT/Action 私有实现。
- /perception/audio_event 和 /perception/voice/enrollment_event 保留 String/JSON。
- /perception/voice/task 保留 marsdog_voice_interaction/srv/VoiceTask。
- waypoint_nav 对 VoiceTask 的既有依赖仍保留；本轮不移动或改名 ROS 类型。
- HTTP 声纹接口、词库和网页资源全部保留。未增加平台级公共业务模块。
- Python 3.10 + 原 lock 独立环境（NumPy 1.26.4）；不与 Action NumPy 2.2.6 合并。

## 验证范围

| 检查 | 原快照 | 导入后 |
| --- | --- | --- |
| 无 ROS 的纯 Python 子集 | 165 passed，无 skip | 165 passed，无 skip |
| Humble 完整单元测试 | 328 passed，无 skip | 328 passed，无 skip |
| 独立原 lock + clean wheel | PASS | PASS |
| ROS Humble 独立 colcon 构建 | PASS | PASS |
| 已安装 Voice mock DDS 事件 + 7 个 service 用例 | PASS | PASS |

165 是 328 的子集，不得相加。首次未 source Humble 的全量运行出现 4 个 rclpy
导入错误，随后根据真实测试依赖 source 现有 Humble，未修改测试或伪造 rclpy。
完整单元测试并不代表真实 ROS transport；后者由独立安装的 mock probe 提供。

wheel 验证在离开源码的临时目录，从原 pyproject/lock 恢复 runtime，再安装 wheel
并执行 uv pip check；核对配置/launch/static hash、82 个词库组、156 条标准语句、
HTTP OpenAPI schema 和包入口元数据。未启动 HTTP 服务器。纯 Python wheel
原本不包含 ARM 库或 ROS 生成的 srv；这些由 ROS 构建验证，不改变原打包边界。

ROS probe 使用原有 event mock provider、临时数据目录、关闭 HTTP/音频调试，
随机 localhost 测试域和随机业务端点。测试 start/hold/state/release/unsupported/
invalid-JSON/stop，以及原 MockEventProvider 的 SIT 事件经真实 DDS String/JSON
接收。两个测试节点在同一测试进程中，未运行真实 BT/Action，不是全机器人闭环。
生产配置没有启动。测试使用既有 Fast DDS loopback UDP profile，不能据此声称
生产默认 DDS discovery 问题已解决。

证据：validation/p4-voice。原始失败日志、构建与临时安装日志在 retained
migration 工作区及 out/，不混入平台源码。

## 可复现命令

在平台根目录，用已有 Python 3.10 和 uv：

```bash
uv sync --project modules/voice --locked --no-install-project --extra dev --python /usr/bin/python3.10
python3 -B tools/check_voice_tests.py --mode pure
python3 -B tools/check_voice_install.py --uv uv
# 以下需要已安装的 /opt/ros/humble；脚本不安装系统 ROS：
python3 -B tools/check_voice_tests.py --mode humble
python3 -B tools/check_voice_ros.py --uv uv
```

本机设置 UV_CACHE_DIR=/home/elephant/MarsDog/migration/.cache/uv 后可离线复现。
Humble 构建工具仍使用 platform/humble-build-tools 的独立 lock/env。
源快照复验可向三个脚本传 --source 和不同 --output，避免覆盖已保存证据。

新增 .github/workflows/voice.yml 只承诺纯 Python 子集、wheel 和接口/资源保护。
其本地命令已验证；没有 remote、hosted CI 或分支保护。完整 Humble suite 与
ROS mock gate 需要已有 Humble host。不得把 Python CI 宣称为板端验收。
角色 ownership 暂由 Voice 模块维护者负责，真实账号 UNKNOWN，不杜撰 CODEOWNERS。

## 运行路径和第三方边界

所有默认配置字节保持不变，但移动目录会改变相对路径所指向的实际位置：

| 配置项 | 原源码默认解析目标 | 平台源码默认解析目标 |
| --- | --- | --- |
| ../../models/... | /home/elephant/MarsDog/models/... | /home/elephant/MarsDog/marsdog-platform/modules/models/... |
| ../data | 原 Voice 仓库/data | modules/voice/data |
| ../lib/librkllmrt.so | 原 Voice 仓库/lib/librkllmrt.so | modules/voice/lib/librkllmrt.so |

ROS 安装后的相对路径以 install 中 share/marsdog_voice_interaction/config 为基准。
因此生产切换必须使用明确的外部 config_path，核对模型绝对路径、设备名和原
storage.root。不能只凭配置字节没变就宣称部署路径等价。没有复制或创建模型，
没有迁移声纹/WAV/embedding 数据，也没有启动生产默认入口。

ROS 启动应明确设置 MARSDOG_PYTHON 到 modules/voice/.venv/bin/python，避免在
monorepo 根目录误选其他环境。直接 main 默认 config/voice.yaml 仍依赖 cwd；
保留原行为，正式启动应传明确 config_path。

lib/librkllmrt.so 是原历史中的 ARM64/aarch64 第三方二进制，不是 MarsDog 自研
实现，随历史原样保留。版本/来源许可证证据尚待板端发布核实（UNKNOWN）；不将
它执行于 x86，也不把 Python wheel 成功等同于 RK3588/NPU 模型成功。

## 下一步

转入 Vision 原锁环境和原测试 gate，再决定历史导入。robot_ws/rtabmap_ws、
真实 battery producer、Nav2 生产配置、设备模型验收及实际 owner 账号仍待后续。
