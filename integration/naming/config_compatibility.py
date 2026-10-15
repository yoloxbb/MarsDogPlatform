"""Narrow, frozen semantic checks for explicitly reviewed post-migration YAML edits."""
import hashlib
import json
from pathlib import Path
from copy import deepcopy

FIXTURE = Path(__file__).with_name("config_compatibility.json")
ASSET_FIXTURE = Path(__file__).with_name("asset_compatibility.json")


def assert_reviewed_asset(contents, record, original_sha256):
    """Pin a reviewed existing revision; do not claim original behavior parity."""
    assert record['scope'] == 'preserved_preexisting_revision'
    assert record['original_sha256'] == original_sha256, 'historical source evidence changed'
    assert hashlib.sha256(contents).hexdigest() == record['effective_sha256'], 'reviewed asset revision changed'


def semantic_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def assert_reviewed_config(value, record, original_sha256):
    # Never replace the historical migration evidence with current file hashes.
    assert record["original_sha256"] == original_sha256, "historical source evidence changed"
    if "path_changes" in record:
        restored = deepcopy(value)
        for change in record['path_changes']:
            cursor = restored
            for key in change['path'][:-1]:
                assert isinstance(cursor, dict) and key in cursor, 'default config semantics changed'
                cursor = cursor[key]
            key = change['path'][-1]
            assert isinstance(cursor, dict), 'default config semantics changed'
            assert (key in cursor) is change['after_present'], 'default config semantics changed'
            if change['after_present']:
                assert semantic_sha256(cursor[key]) == semantic_sha256(change['after']), 'default config semantics changed'
            if change['before_present']:
                cursor[key] = deepcopy(change['before'])
            else:
                cursor.pop(key, None)
        assert semantic_sha256(restored) == record['original_semantic_sha256'], 'default config semantics changed'
    elif "timeout_overrides" in record:
        restored = deepcopy(value)
        section = record.get('timeout_section', 'behaviors')
        assert section in ('behaviors', 'audio_direct'), 'unknown reviewed timeout section'
        # Accept only the explicitly reviewed scalar changes. Reversing them
        # must recover the original semantics, including every unrelated field.
        for name, change in record["timeout_overrides"].items():
            actual = restored[section][name]["timeout_sec"]
            assert type(actual) in (int, float) and actual == change["after"], "default config semantics changed"
            restored[section][name]["timeout_sec"] = change["before"]
        assert semantic_sha256(restored) == record["original_semantic_sha256"], "default config semantics changed"
    else:
        assert semantic_sha256(value) == record["effective_semantic_sha256"], "default config semantics changed"


def restore_reviewed_interface_names(contents, relative_path):
    """Reverse only approved endpoint replacements before historical asset checks."""
    records = json.loads(Path(__file__).with_name("interface_migration.json").read_text())["assets"]
    record = records.get(relative_path)
    if record is None:
        return contents
    assert hashlib.sha256(contents).hexdigest() == record["after_sha256"], "interface migration asset changed"
    for replacement in record["replacements"]:
        contents = contents.replace(replacement["after"].encode(), replacement["before"].encode())
    assert hashlib.sha256(contents).hexdigest() == record["before_sha256"], "interface migration preimage changed"
    return contents
