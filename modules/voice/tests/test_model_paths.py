"""Model storage must resolve identically in source and installed layouts."""
from pathlib import Path

import pytest

from marsdog_voice_interaction.utils import model_paths


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    monkeypatch.delenv("MARSDOG_VISION_MODEL_DIR", raising=False)


@pytest.mark.parametrize("relative", [
    "modules/voice/config/production.yaml",
    "out/local/install/voice/share/voice/config/production.yaml",
])
def test_source_and_install_use_platform_root_without_existing_models(
    tmp_path, monkeypatch, relative,
):
    checkout = tmp_path / "renamed-checkout"
    marker = checkout / "platform/modules.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    monkeypatch.chdir(tmp_path)
    assert model_paths.model_root(checkout / relative) == checkout / "models"
    assert not (checkout / "models").exists()


def test_external_config_uses_package_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    marker = checkout / "platform/modules.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    monkeypatch.setattr(model_paths, "__file__", str(checkout / "out/install/pkg/model_paths.py"))
    assert model_paths.model_root(tmp_path / "custom.yaml") == checkout / "models"


def test_external_root_wins_even_if_directory_does_not_exist(tmp_path, monkeypatch):
    external = tmp_path / "shared model assets"
    monkeypatch.setenv("MARSDOG_MODEL_DIR", str(external))
    assert model_paths.model_root(tmp_path / "custom.yaml") == external


def test_relative_environment_root_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSDOG_MODEL_DIR", "models")
    with pytest.raises(ValueError, match="absolute"):
        model_paths.model_root(tmp_path / "custom.yaml")


def test_detached_wheel_requires_explicit_root(tmp_path, monkeypatch):
    monkeypatch.setattr(model_paths, "__file__", str(tmp_path / "site-packages/pkg/model_paths.py"))
    with pytest.raises(ValueError, match="set MARSDOG_MODEL_DIR"):
        model_paths.model_root(tmp_path / "custom.yaml")
