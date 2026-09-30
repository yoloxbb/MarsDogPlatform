# 源码交付与板端接入

当前可交付的是统一主仓源码、历史、依赖锁、接口和软件验收。
已有 x86_64 WSL 开发组合；开发板型号、CPU ABI、OS、ROS 安装与厂商 NPU/SDK 版本
仍 UNKNOWN。Lite3 是机器人目标，不等于开发板配置已知。
没有实机不妨碍模块开发、PR 和软件流程验证。

## 可验证的离线源码包

先提交已经评审的本地变更。以下导出要求工作区干净，目标目录必须不存在：

~~~bash
python3 tools/source_handoff.py create --directory out/handoff/source-bundle \
  --archive-dir /absolute/path/to/archives
python3 tools/source_handoff.py verify --directory out/handoff/source-bundle
~~~

导出包含当前主仓所有 refs 的 Git bundle 和 manifest。
显式给 --archive-dir 时，附带 sources.lock.json 要求的两个固定 vendor bundle，
逐文件验证 SHA256；不附加整个历史工作目录。
不带 --archive-dir 也可导出主仓，但接收方需另行取得清单中的固定归档。

这是内部交接；厂商库/历史内容的外部分发许可尚待确认，不自动上传或发布。
哈希用于完整性校验，不代表签名或来源认证。

将整个输出目录复制到新主机，先用可信工具验证，再在新位置：

~~~bash
git clone /absolute/path/to/source-bundle/marsdog-platform.bundle marsdog-platform
cd marsdog-platform
python3 tools/dev.py check
~~~

首次 ROS prepare 可用包内 vendor-archives。也可设置 MARSDOG_ARCHIVE_DIR；
未指定时默认只查 .cache/vendor-archives，不查原仓旁边的目录。

bundle 保留主仓已有历史，不复制 .venv、out、.external、模型、设备配置或下载缓存。
主仓的历史来源记录/commit maps 随版本保留；原始独立仓完整档案另行保管。
源码 bundle 不是完整的离线依赖镜像；首次 Python/ROS 依赖下载仍需要网络或匹配的缓存。

## 已完成的本轮验收

源码 2468639 已经真实导出、校验、在独立目录克隆，并完成五模块独立环境/测试/
干净 wheel、四 vendor 和默认 ROS 15 包从零构建及 doctor/smoke。
本机源码验收包是 out/handoff/source-bundle-2468639；
含最新证据和交接的最终包为 out/handoff/source-bundle-final，以 manifest 为准。
详见 [P7 验收](../migration/P7_DEVELOPER_PLATFORM.md)。
这些本机输出目录不进入 Git；接收方取得实际输出目录后按上文校验。

## 开发板接入顺序

1. 记录板型号、uname -m、OS、Python/ROS 版本、NPU 驱动/runtime 及 Lite3 SDK/IDL 来源。
   未知字段保持 UNKNOWN，不用 WSL 探测值填板端清单。
2. 在板端克隆同一源码版本。按该平台复核各模块锁中的 wheel/ABI 支持和系统库；
   Voice 的 Python 3.10、RKLLM，Vision 的 RKNN/RGA 等各自处理，不合成一个大环境。
3. 为确认的板端目标增加独立的构建/运行配置。当前 prepare 的 x86_64 Debian
   依赖和 bootstrap_uv 的 x86_64 可执行文件不可直接当作 ARM 工具链。
4. 在板端重新创建 .venv、colcon build/install；严禁复制 WSL 的这些二进制产物充当部署。
   保留原 RKLLM/NPU 推理路径，CPU 只承担开发回放；模型由独立资产清单交付。
5. 先做 imports/IDL/构建/进程启停与模拟 I/O，之后逐一接入实际传感器/导航/Lite3。
   外部运动/嵌入式协议以现有调用和厂商证据确认，不实现猜测的内部控制器。
6. 最后验证设备上的取消、急停边界、时延与实际动作结果，再形成设备验收记录。
   当前软件流程通过不自动解除已有 Lite3 动作门限。

## 团队接管需要的外部信息

| 信息 | 当前状态 | 影响 |
| --- | --- | --- |
| 主仓远端 URL、访问权限、公开范围 | UNKNOWN | push、PR、保护分支、hosted CI |
| 真实 maintainer 账号/团队 | UNKNOWN | CODEOWNERS 和必需评审绑定 |
| 开发板 OS/ABI/SDK/NPU runtime | UNKNOWN | 板端依赖与 profile |
| Lite3 实际设备/传感器/SDK | 不可用 | 实机验收 |
| 保留第三方/厂商内容的分发许可 | 部分 UNKNOWN | 对外发布 |

这些是外部配置/验收条件，不阻塞当前主仓开发；不能用虚构账号、硬件成功或许可结论填补。
