# Behavior candidate signal from upstream nodes
# Published to /behavior_signal by upstream perception/need/emotion nodes

string  behavior_id        # Unique signal ID
string  behavior_name      # Behavior to execute (e.g. "playBow", "seek_food_or_water")
int32   priority_level     # 0 (highest) to 6 (lowest/idle)
float64 value              # Activation strength 0-100
float64 confidence         # Upstream detection confidence 0-1
string  need_type          # emotional / physiological / external / survival / system / idle
string  source_emotion     # Source emotion name if need_type=emotional (Joy/Fear/...)
string  params_json        # JSON-encoded extra params
float64 timeout_sec        # Max execution time
float64 cooldown_sec       # Min time between repeats
