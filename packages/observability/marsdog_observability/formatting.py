"""Human rendering is a view of the canonical record, never a second log schema."""
import json


def render_record(row):
    context = row.get("context", {})
    details = {**row.get("fields", {}), **context}
    message = row.get("message", "")
    body = (message + " " if message else "") + (json.dumps(details, ensure_ascii=False) if details else "")
    rendered = f'{row["timestamp"]} {row["level"]:7} {row["component"]:9} {row["event_name"]} {body}'.rstrip()
    return rendered + ("\n" + row["exception"] if row.get("exception") else "")
