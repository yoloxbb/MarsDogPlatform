"""Exercise real content/mode drift detection on throwaway files, never original repos."""
import importlib.util
import os
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("baseline_lib", TOOLS / "baseline_lib.py")
LIB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIB)


def test_detects_idl_content_drift(tmp_path):
    path = tmp_path / "Example.srv"
    path.write_text("string task_id\n---\nbool success\n")
    expected = {"Example.srv": LIB.file_record(path, "100644")}
    assert LIB.compare_files(tmp_path, expected) == []
    path.write_text("int32 task_id\n---\nbool success\n")
    assert LIB.compare_files(tmp_path, expected) == [
        {"path": "Example.srv", "reason": "sha256"}
    ]


def test_detects_removed_configuration(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("enabled: false\n")
    expected = {"config.yaml": LIB.file_record(path, "100644")}
    path.unlink()
    assert LIB.compare_files(tmp_path, expected) == [
        {"path": "config.yaml", "reason": "missing"}
    ]


def test_detects_lost_launcher_executable_mode(tmp_path):
    path = tmp_path / "launcher"
    path.write_text("#!/usr/bin/python3\n")
    path.chmod(0o755)
    expected = {"launcher": LIB.file_record(path, "100755")}
    path.chmod(0o644)
    assert LIB.compare_files(tmp_path, expected) == [
        {"path": "launcher", "reason": "working_mode"}
    ]


def test_hashes_symlink_target_without_following_it(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_text("same")
    second.write_text("same")
    link = tmp_path / "current"
    link.symlink_to("first")
    expected = {"current": LIB.file_record(link, "120000")}
    link.unlink()
    link.symlink_to("second")
    assert LIB.compare_files(tmp_path, expected) == [
        {"path": "current", "reason": "sha256"}
    ]
