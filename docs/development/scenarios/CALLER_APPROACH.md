# 叫过来与唤醒靠近场景规格

目标是让团队用一条跨听觉、视觉、BT、Action 和导航的场景验证协作边界。当前状态为**架构与接口基线已明确，现有视觉到导航几何链路未接通**。本规格区分两种已有入口，不将其会话和身份规则合并。

功能牵头角色为 BT，执行接入由 Action 负责，Vision 提供目标观测，导航提供三维定位与导航能力。Emotion/Needs 由 BT 技术 owner 兼任维护；本场景保持现有结算映射，不新增结算。

## 两种入口的实际路径

| 入口 | 当前路径 | 关键差异 |
| --- | --- | --- |
| 明确口令“过来” | `EVT_VOICE_COMMAND_COME` + `CMD_COME_HERE` → `command_come_here` → `come_to_owner` → `ACT_INTERACT_APPROACH_OWNER` | Action 从新鲜视觉事件绑定人体轨迹；不能把函数或行为名中的 owner 解读成已验证身份 |
| 硬件唤醒后的靠近 | `respond_owner_call` 转向 → 声纹身份与目标查询 → `approach_voice_caller` → `ACT_INTERACT_APPROACH_VOICE_CALLER` | 保留 wake_id、interaction_id、声纹授权和严格目标锁；会话继续经过 WAITING |

明确口令当前配置 timeout 为 170 秒。人物接近适配器当前最小保留距离为 1.5 米。它们是已有参数，不在本规格中作为所有机器人通用的物理保证，也不在本轮修改。

## 2026-10-13 显式新接口

新增场景参数 `approach: {mode: visual|local_nav|map_nav, unit_id: ...}`，详见
[靠近接口契约](../../../interfaces/application/approach/README.md)。纯视觉复用原闭环；
local_nav / map_nav 通过新增 locate_person_geometry 调用现有 LocateFromBbox，再分别调用
ExecuteLocalMotion 或 NavigateToPose。默认旧路由保留，场景配置显式选择后进入新链。
局部模式仍需启用现有 local_motion 能力和 map↔odom TF；裁切双目没有原图对齐证据时拒绝。
固定点接近和原授权规则保留；持续追踪不在本次接口中隐式启用。

新增单测覆盖生产帧 Header、ROI、新鲜度、三模式路由、定位取消及停止恢复锁；
独立契约和 DDS 测试的结果以第四批验证记录为准。深度／TF 服务在 DDS 测试中是替身，实机待验。

## 保留的旧入口与历史接入断点

1. `VisionInteractionNode._locate_person_once` 返回 `{ok, target_id, target}`；目标查询不生成地图坐标。
2. `Ros2PersonApproachTransport.locate` 只向 VisionTask 传 `target_id`。
3. `PersonNavApproachAdapter.execute_task` 对上述视觉目标结果明确返回 `visual_target_only_no_navigation_geometry`，不会发送导航 Goal。
4. 独立的 `/person_3d_localization/locate_from_bbox` 已有 `LocateFromBbox` 接口，但当前 transport 没有调用它。

对应的 Action 测试 `test_visual_only_target_result_fails_without_navigation` 和 Vision 测试 `test_locate_person_once_returns_a_current_visual_target_only` 验证的是当前拒绝边界。几何替身返回成功的 Action 单测不能证明真实 Vision→三维定位→Nav2 已连通。

## 原设计约束（新接口继续遵循）

保留 VisionTask 的当前公开语义。由 Action 侧的人物定位适配端口协调目标观测与现有 `LocateFromBbox` 服务，导航模块继续拥有深度、CameraInfo、TF 和目标点计算。先完成下列数据契约，再编写实际桥接：

| 数据或约束 | 提供方与要求 |
| --- | --- |
| 稳定目标引用 | Vision 提供同一 epoch 的 target_id、跟踪状态和新鲜度；Action 在查询和执行前校验 |
| 检测源图像 Header | Vision 明确产生该 bbox 的原始图像 stamp、frame_id；不得使用服务调用时刻代替 |
| 原图 bbox | Vision 明确原图尺寸、坐标单位及缩放/letterbox 还原；Action 不从含义不明的 x/y/w/h 猜测转换 |
| 深度与标定 | 导航校验 bbox 与对齐深度、CameraInfo 的像素坐标一致；使用实际标定 |
| 几何计算 | 复用 LocateFromBbox 的状态码、有效深度比例和 map 坐标目标；无深度或 TF 失败明确拒绝 |
| 任务关联 | Action 保持 target_id、会话代次与取消状态；迟到结果不得启动导航 |
| 运动结束 | Action 等待导航终态并使用既有底盘停止确认；未知终态保留恢复约束 |

现有服务依据：[三维定位接口](../../../robotics/ros2/src/person_3d_localization/docs/UPPER_LAYER_INTERFACE.md)。目标追踪查询当前能否提供满足这些要求的同帧数据，需要以生产路径验证，不能仅凭测试样例中的字段认定。

该切片先使用替身验证字段、时间、错误和取消，再进行隔离 DDS，最后安排实机。默认配置和已有拒绝边界在验证完成前保留。

## 验收矩阵

| 编号 | 场景 | 必须观察到 | 当前证据或剩余工作 |
| --- | --- | --- | --- |
| CA-01 | 合法口令 / 唤醒 | 两条入口各自满足原授权规则；重复输入不重复发 Goal | BT 会话及 Runtime 单测；真实音频全链仍待验收 |
| CA-02 | 新鲜且稳定的目标 | epoch 和 target_id 一致；旧目标或代次拒绝 | Vision 快照与 BT 选人单测 |
| CA-03 | 当前只返回视觉目标 | 明确失败；导航调用次数为零 | Action 与 Vision 单测已存在 |
| CA-04 | 同帧 bbox、深度及 TF 有效 | 几何结果对应锁定目标；需要移动时仅发一个导航 Goal | 桥接尚未实现；已有几何替身测试不替代此项 |
| CA-05 | 无深度、无标定、坏 bbox、TF 不可用 | 返回可诊断错误；不发送运动 Goal | 导航侧测试与桥接契约需共同验证 |
| CA-06 | 查询或执行中取消 | 迟到几何结果不触发导航；取消 ACK 后仍保留任务归属至终态 | Action 取消单测；几何桥接取消待补 |
| CA-07 | 旧进程结果、目标丢失或换人 | 不把迟到结果绑定给新目标；执行中目标丢失策略须明确 | BT/Vision 有局部覆盖；全链故障注入待补 |
| CA-08 | 导航返回未知终态 / 停止未确认 | 不宣告到达，不自动解除恢复锁，不启动下一运动 | Action 恢复单测；设备停止仍需实机证据 |
| CA-09 | 正常结束或失败 | 每个已接受 Goal 有一次终态或明确恢复处置；按原规则处理会话 | BT Runtime 单测；完整会话闭环待集成 |
| CA-10 | 内部状态更新 | 只按现有 BEHAVIOR_ACTION_MAP 和有效证据结算 | 本轮没有新增情绪或需求结算规则 |

尚需产品明确的行为语义：一次定位后是否仅走向固定点，或在运动中持续追踪；目标丢失后的停止/重试条件；明确口令是否要求主人身份；成功后的提示与等待方式。当前实现中的不同规则保持不变，不能在桥接过程中顺手统一。

## 复现已覆盖的单元边界

以下在仓库根目录执行，使用现有独立环境。所选用例使用替身对象；加载 Humble 为导入真实类型，不代表启动 ROS 通信或实机验收。

```bash
python3 -B tools/dev.py check
python3 -B tools/capabilities.py --output out/architecture-rollout/capabilities
(
  unset PYTHONHOME VIRTUAL_ENV
  source /opt/ros/humble/setup.bash
  export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MARSDOG_LOG_DISABLED=1
  export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=218 QT_QPA_PLATFORM=offscreen
  cd modules/vision
  PYTHONPATH="$PWD:$PYTHONPATH" .venv/bin/python -B -m pytest tests/test_visual_locate_task.py tests/test_wake_target_snapshot.py -q -p no:cacheprovider
)
(
  unset PYTHONHOME VIRTUAL_ENV
  source /opt/ros/humble/setup.bash
  export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MARSDOG_LOG_DISABLED=1
  export ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=218 QT_QPA_PLATFORM=offscreen
  cd modules/voice
  PYTHONPATH="$PWD:$PYTHONPATH" .venv/bin/python -B -m pytest tests/test_session_recovery.py -q -p no:cacheprovider
)
(
  export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MARSDOG_LOG_DISABLED=1
  cd modules/behavior
  PYTHONPATH="$PWD" .venv/bin/python -B -m pytest tests/test_voice_engagement.py marsdog_behavior/tests/test_runtime_architecture.py -q -p no:cacheprovider
)
(
  export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MARSDOG_LOG_DISABLED=1
  cd modules/action
  PYTHONPATH="$PWD" .venv/bin/python -B -m pytest tests/test_person_nav_approach_adapter.py -q -p no:cacheprovider
)
```

完整 DDS、安装来源和进程恢复门禁沿用 [业务场景矩阵](../BUSINESS_SCENARIOS.md)。代码接入后必须增加真正跨 Vision、几何服务和导航的测试，再将 CA-04 等剩余项升级为通过。
