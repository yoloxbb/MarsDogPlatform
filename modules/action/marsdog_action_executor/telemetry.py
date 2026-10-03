"""Read-only logging projections of the public ExecuteBehavior request."""
import json


def goal_fields(request):
    fields = {key: getattr(request, key, None) for key in
              ("goal_id", "behavior_id", "behavior_name", "priority_level")}
    try:
        params = json.loads(getattr(request, "params_json", "{}"))
        if isinstance(params, dict):
            fields.update({key: params[key] for key in
                           ("interaction_id", "utterance_id", "wake_id", "target_id")
                           if key in params})
    except (ValueError, TypeError):
        pass
    return fields
