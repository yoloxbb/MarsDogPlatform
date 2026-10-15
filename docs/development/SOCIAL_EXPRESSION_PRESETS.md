# 社交表达预设与能力缺口处置

2026-10-13：根据用户“缺口可以先自己补”的授权，补入 33 个可调整的表达预设。
原有 74 个动作计划逐字保留；新增配置合并后共 107 个计划、183 个 ACT 单元。
下面是软件默认设计，不代表真机验收；Lite3 的姿态代偿仍按原 allow_proxies、allow_unverified、enabled 等策略执行。

## 配置与结果边界

- `modules/action/config/behavior_tree_actions.yaml` 保留原计划；`behavior_presets.yaml` 专门存放新增表达预设，不能覆盖原名。
- 同步维护 BT 的 `behaviors.yaml` 与 `event_intent_map.yaml`：候选优先取事件超时，不能只修改行为目录。当前普通预设预算 15 秒、dance 25 秒；控制器自身动作预算仍由 action_catalog 约束。
- 每阶段 required=true、failure_policy=abort；任何必需动作失败、超时或取消都不能成为成功。重复名称、空动作、假布尔序号、预算不足在加载时拒绝。
- `ExecuteBehavior` 的 metadata_json 增加可选 `completion_scope=expression_only` 和 `preset_version=1`，原 IDL、状态名及请求字段不变。SUCCESS 只表示必需表达阶段完成。
- 这些名称不进入需求结算表，不产生需求 STARTED/COMPLETED，不减少饥饿、电量、社交等内部需求；原事件影响情绪的路径不变。
- stay_home / wait_return 目前表示短暂原地确认；持续看家、长期等待及主人回家结束条件需要另设持久任务，不能从此预设的 SUCCESS 推断。
- 不主动导航、不选择新的人或物、不报告疼痛/位置/学习事实；传感器接触、真实摇尾和拥抱都不能由姿态代偿证明。

## 新增预设

| 行为 | 默认语义 |
| --- | --- |
| comfort_soothe | 安抚回应：轻柔低身示意 |
| comfort_reassure | 安抚回应：短暂安静停留 |
| pet_head | 邀请摸头的姿态表达，不确认已经发生触摸 |
| hug | 邀请拥抱的姿态表达，不主动贴靠或确认身体接触 |
| refuse | 回应用户拒绝：保持当前姿态并停留 |
| refuse_play | 回应用户不想玩：保持当前姿态并停留 |
| dance | 简短舞蹈预设：左右扭腰后抬头；受既有底盘策略限制 |
| stay_home | 留守指令的短暂原地确认；不建立持续看家任务 |
| wait_return | 等待指令的短暂原地确认；不声称已经等到主人归来 |
| greet_return | 归来问候：友好姿态后轻柔低身示意 |
| farewell_bye | 告别的友好姿态表达 |
| farewell_goodbye | 告别的友好姿态表达 |
| respond_thought | 思考状的姿态回应，不生成事实性心理报告 |
| respond_comfort | 舒适询问的轻松姿态回应，不推断传感器状态 |
| respond_like | 喜好询问的友好姿态回应，不写入偏好记忆 |
| respond_fun | 玩耍询问的友好姿态回应，不写入偏好记忆 |
| respond_understand | 听到询问后的注意姿态，不声称语义理解通过验证 |
| show_skill | 展示已有左右扭腰动作，非能力清单播报 |
| tired | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| annoyed | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| downcast | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| depressed | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| stressed | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| lonely | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| unwell | 回应主人负面感受的原地低头陪伴表达；不导航或推断健康状况 |
| cheerful | 回应主人积极感受的友好姿态表达 |
| happy | 回应主人积极感受的友好姿态表达 |
| great_form | 回应主人积极感受的友好姿态表达 |
| great | 回应主人积极感受的友好姿态表达 |
| relaxed | 回应主人轻松感受的舒展姿态表达 |
| wonderful_day | 回应主人积极感受的友好姿态表达 |
| lucky | 回应主人积极感受的友好姿态表达 |
| respond_food_preference | 食物偏好询问的注意姿态，不选择食物或结算饥饿 |

## 仍待接入的能力

16 个名称继续被 Action 拒绝，不注册空计划或 mock-success。名称和路由保留，产品台账已由 UNDECIDED 改为 deferred_integration，并明确 owner 与所需证据。兼容例外仅保留这 16 条；已有 33 条从例外中移除。生成 capability_backlog.json 会带上原因和证据，不会再次丢成待决策。

| 行为 | 缺口 | 所需证据 |
| --- | --- | --- |
| care_inquire | 事实问答需要可信状态和回答接口，不用姿态表达代替状态事实 | fresh_state_observation, state_to_voice_response, response_playback_result |
| find_dad | 家庭称谓与视觉身份尚无权威绑定，不替换成任意人 | family_role_identity_binding, identity_locked_search, localized_target_and_cancel_ack |
| find_mom | 家庭称谓与视觉身份尚无权威绑定，不替换成任意人 | family_role_identity_binding, identity_locked_search, localized_target_and_cancel_ack |
| bring_to_me | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| give_me | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| go_fetch | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| bring_back | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| fetch_ball | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| find_toy | 缺少目标实例选择及取放/找到结果闭环，不替换成随机物体动作 | object_instance_selection, target_localization, grasp_release_or_search_result_feedback, cancel_and_stop_confirmation |
| report_activity | 事实问答需要可信状态和回答接口，不用姿态表达代替状态事实 | fresh_state_observation, state_to_voice_response, response_playback_result |
| report_location | 事实问答需要可信状态和回答接口，不用姿态表达代替状态事实 | fresh_state_observation, state_to_voice_response, response_playback_result |
| report_state | 事实问答需要可信状态和回答接口，不用姿态表达代替状态事实 | fresh_state_observation, state_to_voice_response, response_playback_result |
| respond_learned | 缺少学习任务身份和完成记录，不能用友好动作表示已经学会 | learning_task_id, persisted_learning_result, state_to_voice_response |
| eat_meal | 饮食仪式与真实需求满足尚无统一结果契约，不用低头动作结算饥饿 | feeding_scenario_contract, food_waypoint_or_target, observed_or_explicitly_simulated_need_result |
| eat_snack | 饮食仪式与真实需求满足尚无统一结果契约，不用低头动作结算饥饿 | feeding_scenario_contract, food_waypoint_or_target, observed_or_explicitly_simulated_need_result |
| eat_canned_food | 饮食仪式与真实需求满足尚无统一结果契约，不用低头动作结算饥饿 | feeding_scenario_contract, food_waypoint_or_target, observed_or_explicitly_simulated_need_result |

## 后续修改与验证

新增表达编辑预设文件；涉及新控制协议、真实接触、找人取物或需求结算的实现进入正式任务计划，不能沿用 expression_only 来冒充任务成功。已解决的延期能力需同步台账和精确兼容例外，检查器拒绝过期状态。

运行 `tools/check_identifiers.py --refresh --python modules/action/.venv/bin/python` 后，再执行 `tools/dev.py check`、Action/Behavior 全量测试、音频与结果契约。变更取消边界还需 callback、安装后 DDS 所有权和关闭停车检查。测试用本地隔离 ROS domain 与模拟 I/O。

取消在 Stage 入口被观察到时，入口直接返回 canceled，不再启动下一动作或 stationary hold；正在执行单元的停止和确认仍由原适配器负责。取消 ACK 不交接底盘所有权，仍等待终态。

历史迁移审计通过 integration/naming/config_compatibility.json 分别精确登记行为目录与语音入口的 33 个 timeout 标量。反向恢复这组标量后必须重现原始配置语义；原始 SHA-256 和冻结迁移记录不变。其他字段变化仍使审计失败。
