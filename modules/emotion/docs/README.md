# Marsdog 文档导航

本目录包含当前接口契约、计算规则、联调指南和历史迁移资料。行为执行由外部
行为模块负责，本项目只维护虚拟时间、内部需求、情绪、性格参数和 ONE1000
临时摸头输入。

## 当前权威文档

| 文档 | 用途 |
|---|---|
| [ROS2 Topic 契约](ros2_topic_contract.md) | Topic、QoS、JSON 字段和事件命名的唯一对外契约 |
| [内部需求与情绪更新逻辑](internal_need_emotion_update_logic.md) | 当前需求、情绪、性格和时间计算规则 |
| [Python API](api.md) | 纯 Python 核心系统的公共调用接口 |
| [当前实现总结](current_implementation_summary.md) | 已实现范围、系统边界和快速交接入口 |
| [行为结果联调](behavior_result_event_alignment.md) | 外部行为模块的结果回传和需求同等级重发语义 |
| [情绪事件映射目录](emotion_event_catalog.md) | 由 `configs/emotions.yaml` 自动生成的声音、触摸和视觉基础映射 |

发生内容冲突时，Topic 字段和 QoS 以 `ros2_topic_contract.md` 为准，计算数值
以 `configs/` 和 `internal_need_emotion_update_logic.md` 为准，代码与测试是最终
可执行基线。

## 专项联调

| 文档 | 用途 |
|---|---|
| [时间压缩测试](time_compression_test_guide.md) | 1-100 倍、凌晨加速和完整一天测试 |
| [ONE1000 摸头联调](2026-08-01_one1000_head_pet_integration_guide.md) | 串口、距离/雷达模式和诊断排障 |
| [感知系统 ROS2 说明](MarsDog感知理解层ROS2说明文档.md) | 外部感知系统提供的视觉、声音、目标和服务接口 |

感知说明是外部系统契约。当前其中的 `/perception/interaction_event` 与本项目
订阅的 `/perception/audio_event` 存在命名差异，联调前需要与感知侧确认实际
Topic。

## 历史迁移资料

以下日期型文档用于记录 V2 协议迁移过程，不作为当前接口的唯一来源：

- [情绪 V2 联调迁移](2026-07-29_emotion_v2_integration_guide.md)
- [内部需求 V2 联调迁移](2026-07-29_internal_need_v2_integration_guide.md)

## 维护规则

1. 修改 Topic、字段、QoS 或事件枚举时，先更新 ROS2 Topic 契约并补测试。
2. 修改阈值、增量、时间窗口或恢复量时，先更新 `configs/` 和计算逻辑文档。
3. 新增日期型迁移文档时，在本页登记，并明确其历史属性。
4. 不在多份文档复制完整 JSON 契约；其他文档通过链接引用权威章节。
5. 修改情绪事件映射后运行 `python3 tools/export_emotion_event_catalog.py`，并用
   `python3 tools/export_emotion_event_catalog.py --check` 检查生成目录。
