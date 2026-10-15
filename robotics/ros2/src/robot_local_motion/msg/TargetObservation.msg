# Identity is mandatory. Header time is the ORIGINAL observation time.
# Sequence increases per (source, target_id); a new producer uses a new source.
std_msgs/Header header
geometry_msgs/Point position
string target_id
string source
uint64 sequence
float32 confidence
bool valid
