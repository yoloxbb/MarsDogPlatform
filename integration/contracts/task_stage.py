"""Service envelope callbacks on real node classes; domain task execution is a test port."""
import json
from types import SimpleNamespace
from unittest.mock import patch
from worker_support import serve


def exercise(stage, cases):
    if stage == "voice":
        from marsdog_voice_interaction.nodes import voice_interaction_node as module
        node_class = module.VoiceInteractionNode
    else:
        from marsdog_vision_interaction.nodes import vision_interaction_node as module
        node_class = module.VisionInteractionNode
    outputs = {}
    for spec in cases:
        calls, traces = [], []
        def run_task(task_type, params):
            calls.append({"task_type": task_type, "params": params})
            if "raise" in spec:
                raise ValueError(spec["raise"])
            return spec.get("result", {"ok": True, "text": "完成"})
        trace = lambda *args, **kwargs: traces.append({"args": list(args), "fields": kwargs})
        context = SimpleNamespace(_run_task=run_task, _trace=trace,
                                  _config={}, _interaction_id="interaction-current")
        request = SimpleNamespace(task_id="task-1", task_type="fixture_task",
                                  params_json=spec["params_json"])
        response = SimpleNamespace()
        with patch.object(module.time, "perf_counter", side_effect=[100.0, 100.125]):
            if stage == "vision":
                with patch.object(module, "vision_trace", side_effect=trace):
                    node_class._handle_task(context, request, response)
            else:
                node_class._handle_task(context, request, response)
        outputs[spec["id"]] = {"response": vars(response), "calls": calls, "traces": traces}
    return outputs, module.__file__


if __name__ == "__main__":
    serve({"voice": lambda request: exercise("voice", request),
           "vision": lambda request: exercise("vision", request)}, allow_ros=True)
