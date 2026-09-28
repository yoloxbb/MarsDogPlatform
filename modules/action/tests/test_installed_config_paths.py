"""Preserve caller/cwd precedence while enabling installed wheel assets."""
import sys
from pathlib import Path

from marsdog_action_executor.config_loader import ConfigLoader, installed_config_dir
from marsdog_action_executor import emotion_display


def prepare_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    installed = installed_config_dir()
    installed.mkdir(parents=True)
    return installed


def test_default_config_uses_prefix_when_cwd_missing(tmp_path, monkeypatch):
    installed = prepare_prefix(tmp_path, monkeypatch)
    assert ConfigLoader().config_dir == installed


def test_cwd_config_preserves_priority(tmp_path, monkeypatch):
    prepare_prefix(tmp_path, monkeypatch)
    (tmp_path / "config").mkdir()
    assert ConfigLoader().config_dir == Path("config")


def test_explicit_missing_path_does_not_silently_use_installed_config(tmp_path, monkeypatch):
    prepare_prefix(tmp_path, monkeypatch)
    explicit = tmp_path / "caller-config"
    assert ConfigLoader(explicit).config_dir == explicit


def test_image_fallback_is_after_existing_source_and_cwd(tmp_path, monkeypatch):
    installed = prepare_prefix(tmp_path, monkeypatch)
    dirs = emotion_display._resolve_image_dirs()
    assert dirs[-1] == installed / "emotion_images"
    assert dirs.index(Path("config") / "emotion_images") < len(dirs) - 1
