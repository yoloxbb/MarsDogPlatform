# /behavior/result_event — terminal result event
#
# Published by marsdog_action_executor when a behavior completes.

string  goal_id
string  behavior_id
string  behavior_name
string  status              # SUCCESS / FAILURE / CANCELED / TIMEOUT
string  reason
float64 reward
float64 duration_sec
string  emotion_delta_json
string  need_delta_json
float64 timestamp
