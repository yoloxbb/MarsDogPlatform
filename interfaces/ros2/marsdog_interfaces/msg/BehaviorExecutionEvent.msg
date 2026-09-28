# /behavior/execution_event — execution state change event
#
# Published by marsdog_action_executor for visualization / logging.

string  goal_id
string  behavior_id
string  behavior_name
string  event_type          # STEP_START / STEP_COMPLETE / STAGE_START / STAGE_COMPLETE
string  action_id           # Current action ID (e.g. ACT_TAIL_WAG_FAST)
string  stage_name          # Current stage name
float64 progress            # 0.0 - 1.0
float64 timestamp
