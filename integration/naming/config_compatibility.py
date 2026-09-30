"""Narrow, frozen semantic checks for explicitly reviewed post-migration YAML edits."""
import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).with_name("config_compatibility.json")


def semantic_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def assert_reviewed_config(value, record, original_sha256):
    # Never replace the historical migration evidence with current file hashes.
    assert record["original_sha256"] == original_sha256, "historical source evidence changed"
    assert semantic_sha256(value) == record["effective_semantic_sha256"], "default config semantics changed"
