# 场景显式选择靠近方式

2026-10-13 新增接口。沿用 `ExecuteBehavior.params_json`，不更名或改写既有 ROS IDL。
未提供 `approach` 时保留旧路由。直驱和内部状态都先生成候选，经 BT 仲裁后才进入本接口。

```json
{
  "approach": {"unit_id": "ACT_INTERACT_APPROACH_VOICE_CALLER", "mode": "map_nav"},
  "strict_target_lock": true,
  "allow_target_switch": false,
  "stand_off_distance_m": 1.5
}
```

上例只是新增参数片段。唤醒场景仍须提供原有 wake_id、interaction_id、匹配的声纹身份和绑定目标；
owner 口令仍验证对应行为模板并从新鲜视觉观测选定人体。普通视觉目标的地图／局部模式当前只接受人体。
不能把 owner 行为名解释成视觉已经确认主人身份。

| mode | 实际路径 | 结束依据 |
| --- | --- | --- |
| visual | 原视觉闭环适配器 → 选定底盘 | 原目标锁、距离、丢失和到达保持规则 |
| local_nav | 新增视觉几何查询 → LocateFromBbox → ExecuteLocalMotion(move) | 局部任务真实终态、stop_confirmed 与底盘结算 |
| map_nav | 新增视觉几何查询 → LocateFromBbox → NavigateToPose | Nav2 真实终态与底盘结算 |

`unit_id` 必须在当前行为计划里，且属于允许的靠近单元。含该单元的选择阶段固定选择它，
不会随机选到别的运动接口。`approach` 与 `local_motion` 两种覆盖参数互斥；控制器缺失、无深度、
错误目标、坐标不可用均失败，不自动切换另一种靠近方式。

local_nav 保持现有 `local_motion.yaml.enabled: false` 默认值。部署方启用并把相应 unit_id 加入
allowed_units 后方可调用。局部服务将 map 目标通过 TF 转入 odom；**这一版仍需要 map↔odom TF**，
不等于已经实现无地图定位。地图点位靠近使用定位产生的固定 Pose；已有按名字回家／地点导航入口保持原语义。
两种导航模式均为一次定位到固定点，运动中不重新追人；需要持续跟随时使用对应跟随能力。

## 视觉几何查询

`/perception/vision/task` 新增 `task_type=locate_person_geometry`，params 仍为 `{target_id}`。
固定样例见 [geometry-v1.json](geometry-v1.json)。

- Vision 从**同一次推理的原始检测框与轨迹**建立唯一对应，保留原图尺寸、原始 stamp/frame。
- ROI 为原图像素坐标，绝不把归一化坐标直接当像素，或把服务请求时刻当拍摄时刻。
- 被保留的旧轨迹、歧义匹配、过期帧、缺原始 Header 或经过双目裁切但没有原图对齐证据的观测均拒绝。
- 旧 `locate_person_once` 继续返回视觉目标；其响应没有悄悄变成地图坐标。

Action 调用 `/person_3d_localization/locate_from_bbox`。深度、CameraInfo、TF、停靠点计算仍属于
`robotics/ros2/src/person_3d_localization`；Action 只校验结果并派发一个选定模式的导航任务。
任何取消／期限耗尽后的定位结果都不能启动导航；Cancel ACK 不释放运动占用，未知终态保留恢复锁。
局部模式由 LocalMotionAdapter 独占底盘准备与结束，外层不重复调用。

## 验证与边界

`tools/check_approach_tactile_contracts.py` 在独立 Vision / Action 环境验证生产消费字段；
`integration/ros/approach_transport_probe.py` 在 localhost domain 216 用真实 DDS 类型和安装的 Action 适配器
验证成功、无深度、错目标、已靠近、定位取消、导航取消和停止未确认。定位、导航服务与底盘是明确的测试替身。
实机需另验 RGB／深度配准、TF、双目选眼坐标还原、避障及停止距离，不以软件替身代替。
