"""Battery evidence validation for behavior-result settlement, not a BMS driver."""
import math
from numbers import Real

MAX_OBSERVATION_AGE_SEC = 5.0


def battery_percentage(metadata, now):
    """Return a valid measured percentage or None; legacy scalars are insufficient.

    Source labels are provenance, not authentication. The trusted ROS deployment
    must restrict publishers; no production observation adapter is supplied here.
    """
    observation = metadata.get("battery_observation")
    if not isinstance(observation, dict):
        return None
    if type(observation.get("schema_version")) is not int or observation["schema_version"] != 1:
        return None
    if observation.get("simulated") is not False:
        return None
    source = observation.get("source")
    if not isinstance(source, str) or not source.strip():
        return None
    value, stamp = observation.get("percentage"), observation.get("observed_at")
    if any(isinstance(x, bool) or not isinstance(x, Real) for x in (value, stamp, now)):
        return None
    try:
        if not all(math.isfinite(x) for x in (value, stamp, now)):
            return None
    except (OverflowError, ValueError):
        return None
    if not 0 <= value <= 100 or not 0 <= now - stamp <= MAX_OBSERVATION_AGE_SEC:
        return None
    # Conflicting legacy scalars cannot override observation evidence.
    for key in ("energyValue", "energy_value", "batteryValue"):
        if key in metadata and (isinstance(metadata[key], bool)
                or not isinstance(metadata[key], Real) or metadata[key] != value):
            return None
    return int(value)  # Existing Energy API stores integer percentages.
