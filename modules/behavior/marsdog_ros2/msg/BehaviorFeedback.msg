# Behavior result feedback event
# Published to /behavior/result_event by behavior_tree_node

string  behavior_id
string  behavior_name
string  status              # SUCCESS / FAILURE / CANCELED / TIMEOUT
string  result              # COMPLETED / FAILED / TIMEOUT / INTERRUPTED
string  source_event        # trigger event (e.g. "EMO_JOY_HIGH", "NEED_HUNGER_TRIGGERED", "CMD_SIT")
string  reason
float64 reward
string  emotion_delta_json  # JSON map of emotion_name → delta
string  need_delta_json     # JSON map of need_name → delta
float64 timestamp
