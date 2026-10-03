"""Pure report/acceptance functions for recording trials; no module runtime imports."""
import html
import json


def evaluate_trial(data, code):
    """Fail closed on missing evidence, inconsistent outcome or mixed identities."""
    try:
        worker = data["worker"]
        asr = worker["asr"]
        goals, terminals = data["command_goals"], data["command_terminals"]
        events, rejections = data["command_events"], data.get("rejections", [])
        identity = (data["interaction_id"], data["utterance_id"])
        def same_turn(item):
            return (item.get("interaction_id"), item.get("utterance_id")) == identity
        goal_ids = [g["goal_id"] for g in goals]
        terminal_ids = [t["goal_id"] for t in terminals]
        statuses = [str(t["status"]).upper() for t in terminals]
        requested = any(e.get("should_trigger_behavior_tree") is True for e in events)
        outcome = data["outcome"]
        explained = (
            (outcome == "success" and bool(goals) and all(s == "SUCCESS" for s in statuses))
            or (outcome == "action_failed_or_canceled" and bool(goals)
                and any(s != "SUCCESS" for s in statuses))
            or (outcome == "no_dispatch_requested" and not goals and not requested)
            or (outcome == "rejected_before_goal" and not goals and requested
                and any(same_turn(r) and r.get("stage") in {
                    "mapping_rejected", "candidate_rejected", "candidate_discarded", "candidate_expired"
                } for r in rejections)))
        good = (code == 0 and data["status"] == "PASS" and data["worker_returncode"] == 0
                and worker["status"] == "PASS" and data["real_asr_cases"] == 1
                and data["text_fixture_cases"] == 0 and len(asr) == 1
                and asr[0]["kind"] == "real_sensevoice_cpu" and asr[0]["result"]["reason"] == "ok"
                and bool(asr[0]["result"].get("asr_text", "").strip())
                and data["no_hardware_publishers"] is True
                and all(type(pid) is int and pid > 0 for pid in (worker["pid"], data["observer_pid"]))
                and worker["pid"] != data["observer_pid"]
                and all(isinstance(i, str) and i.strip() for i in identity + tuple(goal_ids + terminal_ids))
                and len(goal_ids) == len(set(goal_ids)) and sorted(goal_ids) == sorted(terminal_ids)
                and all(s in {"SUCCESS", "FAILURE", "INTERRUPTED", "CANCELED", "CANCELLED", "TIMEOUT"}
                        for s in statuses)
                and bool(events) and all(same_turn(e) for e in events)
                and all(same_turn(g["params"]) for g in goals)
                and (not goals or requested) and explained
                and isinstance(data["expectation_errors"], list))
        return bool(good), bool(good and not data["expectation_errors"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return False, False


def decision_observations(directory):
    from log_query import read_records
    rows, _ = read_records(directory)
    return [{**row["fields"], **row["context"], "stage": row["event_name"].removeprefix("behavior.").replace(".", "_"),
             "monotonic_ns": row["monotonic_ns"]} for row in rows
            if row["component"] == "behavior" and row["event_name"].startswith("behavior.") and row["kind"] != "diagnostic"]


def write_trial_report(directory, report):
    data = report.get("probe", {})
    rows = decision_observations(directory)
    interaction, utterance = data.get("interaction_id"), data.get("utterance_id")
    linked = [r for r in rows if interaction and r.get("interaction_id") == interaction
              and r.get("utterance_id") == utterance]
    goal_ids = {g["goal_id"] for g in data.get("command_goals", [])}
    goal_ids.update(r.get("goal_id") or r.get("behavior_id") or r.get("candidate_id") for r in linked)
    linked += [r for r in rows if r not in linked and
               (r.get("goal_id") or r.get("behavior_id") or r.get("candidate_id")) in (goal_ids - {None, ""})]
    asr = data.get("worker", {}).get("asr", [])
    for row in asr:
        for key, stage in (("started_monotonic_ns", "asr_started"), ("finished_monotonic_ns", "asr_completed")):
            if row.get(key):
                linked.append({"component": "voice", "stage": stage, "monotonic_ns": row[key],
                               "interaction_id": interaction, "utterance_id": utterance,
                               "elapsed_ms": row.get("elapsed_ms"), "reason": row.get("result", {}).get("reason", "")})
    for observation in data.get("observations", []):
        event = observation.get("payload", {})
        if event.get("interaction_id") == interaction and event.get("utterance_id") == utterance and interaction:
            linked.append({"component": "observer", "stage": "voice_event_received",
                           "event_type": event.get("event_type"), "reason": event.get("intent_source", ""),
                           "monotonic_ns": observation["monotonic_ns"],
                           "interaction_id": interaction, "utterance_id": utterance})
    linked.sort(key=lambda r: r.get("monotonic_ns", 0))
    (directory / "trace.json").write_text(json.dumps(linked, ensure_ascii=False, indent=2) + "\n")
    asr = data.get("worker", {}).get("asr", [])
    transcript = asr[0].get("result", {}).get("asr_text", "") if asr else ""
    started = data.get("submitted_monotonic_ns", 0)
    # Escape all observed strings: recordings/model output are data, never HTML.
    def esc(value):
        return html.escape(str(value), quote=True)
    def pretty(value):
        return esc(json.dumps(value, ensure_ascii=False, indent=2))
    table = []
    for row in linked:
        elapsed = (row.get("monotonic_ns", started) - started) / 1e6 if started else 0
        table.append("<tr><td>%.0f ms</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
                     (elapsed, esc(row.get("stage", "")), esc(row.get("behavior_name", row.get("event_type", ""))), esc(row.get("reason", ""))))
    page = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>MarsDog 录音试用诊断</title><style>
body{font:16px/1.6 system-ui;margin:36px auto;max-width:1150px;padding:0 20px;background:#f7f9fc;color:#17263b}
h1{font-size:28px}section{background:white;padding:20px;margin:20px 0;border-radius:10px}
table{border-collapse:collapse;width:100%}th,td{padding:9px;text-align:left;border-bottom:1px solid #dde3ec}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f7;padding:16px}
</style><h1>录音 → 行为 → 动作</h1>"""
    page += "<p>真实 CPU ASR；已安装节点与 DDS；视觉、底盘及导航为模拟。未做实机或模型精度验收。</p>"
    page += "<section><b>试用检查：</b>%s<br><b>ASR 文本：</b>%s<br><b>动作观察：</b>%s<br><b>错误：</b>%s</section>" % (
        esc(report.get("status")), esc(transcript), esc(data.get("outcome", "incomplete")),
        esc(report.get("error") or data.get("error") or data.get("expectation_errors", [])))
    elapsed = asr[0].get("elapsed_ms") if asr else None
    page += "<p>会话：%s；语句：%s；ASR 计算耗时：%s ms。时间线从预切分 WAV 提交开始，不包含录音/VAD 耗时。</p>" % (
        esc(interaction), esc(utterance), esc(round(elapsed, 1) if isinstance(elapsed, (int, float)) else "unknown"))
    page += "<section><h2>决策时间线</h2><table><tr><th>相对录音提交</th><th>阶段</th><th>行为</th><th>原因</th></tr>"
    page += "".join(table) + "</table></section>"
    for title, value in (("Voice 实际事件", data.get("command_events", data.get("events", []))),
                         ("Action Goal", data.get("command_goals", [])),
                         ("Action 终态（接受 Goal 不等于执行成功）", data.get("command_terminals", []))):
        page += "<section><h2>" + title + "</h2><pre>" + pretty(value) + "</pre></section>"
    from log_query import read_records, select_records, read_health
    unified, read_errors = read_records(directory)
    selected = select_records(unified, interaction=interaction, utterance=utterance) if interaction else []
    health = read_health(directory)
    (directory / "unified-trace.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n")
    page += "<section><h2>五模块统一日志</h2><p>按会话、语句和 Goal 关联；原始记录保留在 structured。</p><pre>" + pretty(selected) + "</pre></section>"
    page += "<section><h2>日志健康（丢弃/写入错误不等于业务成功或失败）</h2><pre>" + pretty({"processes": health, "read_errors": read_errors}) + "</pre></section>"
    report["unified_logging"] = {"records": len(selected), "trace": str(directory / "unified-trace.json"),
                                  "health": health, "read_errors": read_errors}
    (directory / "report.html").write_text(page + "</html>")
    report["diagnostics"] = {"html": str(directory / "report.html"),
                             "trace": str(directory / "trace.json"), "trace_records": len(linked)}
