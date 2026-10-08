# MarsDogVisionInteraction 上游同步记录（2026-10-08）

上游仓库：`/home/marsdog/marsdog_ws/src/MarsDogVisionInteraction`

上游分支：`test/V1.0.0-alpha.1.2`

同步基线：平台 `e49bb13`；上游导入前缀与平台既有 Vision 导入基线对应。

平台工作分支：`codex/merge-visioninteraction-20261008`

原始上游仓库保持未改动。路径转换和提交应用只在临时副本中进行；平台保留原提交作者，
并按上游提交顺序生成以下平台提交。此前导入前缀 `a05dbf4` 对应平台既有导入基线
`8ffa13e`；下表是该前缀之后的六个提交：

| 上游提交 | 平台提交 | 内容 |
|---|---|---|
| `19042581250681df55b5d63b101118112f6273fb` | `a385880` | `locate_person_once` 只返回视觉跟踪候选，移除 Vision 对 SLAM 定位服务的调用 |
| `c8f73d2523efd5805ff011fe2755497f09a51931` | `6e35dae` | 已确认陌生人的姿态事件沿用既有视觉事件名上报 |
| `c959b6728cc5e05b4fd9d9f469cb9d39d35823e9` | `f9978bc` | 优化持续掩面识别和结束判定 |
| `0ada0c16e0584968f7225d52892e6ef9d9d1606a` | `e61a6c8` | 优化抱头触发 |
| `4719cfc994162baff06f7cbf2ba16d3e03a01dae` | `9822a16` | 优化驼背方向和躺卧判定 |
| `59a64e55c8ef6349e2f95aa204861cbf7d77f2e9` | `a6895d5` | 优化蜷缩姿势识别 |

## 平台适配

- 保留 VisionTask ROS 类型、字段、endpoint、取消生命周期和默认配置；
  `locate_person_once` 的成功数据只包含当前跟踪候选，不再包含地图点。
- Action 收到视觉候选响应时以 `visual_target_only_no_navigation_geometry` 失败关闭，
  不发送 Nav2 目标，也不以 bbox 速度或 `/cmd_vel` 代替导航。旧地图定位响应仍按既有兼容分支处理。
- 将 `identity=unknown`、`identity_state=confirmed_unknown` 且仍处于 `tracking` 的
  目标纳入现有姿态事件身份门控；在视觉跨模块基线增加对应固定场景，既有场景观察值未变。
- 在接口登记和生产/消费方文档中记录候选语义、无地图几何后的行为及 SLAM 服务不再由 Vision 消费。

## 验证

- `python3 -B tools/dev.py check`：通过；标识报告为已有缺口状态且无新增错误。
- Vision：405 项通过，3 项 RGA helper 硬件对照明确跳过。
- Behavior：538 项通过，无跳过。
- Emotion：374 项通过（含 156 个子测试），无跳过。
- Action：462 项通过；31 项因 PySide2 或 `rclpy` 不在该纯单测环境而明确跳过。
- `python3 -B tools/check_visual_contracts.py`：通过；Vision 8 组、下游各 34 个场景，
  包括 confirmed-unknown FALL 传播。
- `python3 -B tools/check_vision_ros.py --uv uv`：通过；
  Humble 构建和已安装 mock 服务传输通过，使用合成图像，没有相机、模型或运动硬件。
- `python3 -B tools/check_task_contracts.py`：受环境阻塞。平台锁定的 ROS 补充依赖只支持
  Ubuntu amd64，而本机为 aarch64；`prepare_ros_deps.py` 明确拒绝在该架构解包。此项没有记为通过。

本记录不声称真实相机/模型识别质量、NPU、Nav2 或机器狗运动已验收。由于上游移除了 Vision
地图定位能力，当前 `approach_voice_caller`、`approach_owner`、`come_to_owner` 和
`return_to_owner` 在 Go2/Lite3 路由中都因没有地图几何安全失败，不会发送 Nav2 目标；恢复
导航需要单独提供并验证符合现有边界的几何来源。

## 上游后续提交：RK3588 情绪 benchmark

原 `VisionInteraction` 分支随后在 `59a64e5` 上新增了提交
`a39980e13ae1ef2c70d6c79095b624ddfe005885`（`feat: add RK3588 emotion benchmark harness`）。
该提交没有进入此前的六提交导入，平台现由 `5cfb190` 导入到
`modules/vision/tools/benchmark_emotion_rknn.py`，并增加纯软件回归测试
`modules/vision/tests/test_benchmark_emotion_rknn.py`。

平台适配将默认模型目录接入 `vision_model_directory()`，生成报告放在根目录 `out/` 下；
JAFFE/KDEF 清单、图像和 RKNN 权重仍需由使用者单独提供，没有复制数据集或模型资产。

验证：`python3 -B tools/dev.py check` 通过；`python3 -B tools/dev.py test vision` 为
405 项通过、3 项因没有 RGA helper 明确跳过、0 项失败；benchmark 的 `--help` 与新增
3 项纯软件测试通过。未在本机执行 RKNN/NPU benchmark，也未验证板端模型精度或性能。
