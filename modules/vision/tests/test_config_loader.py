from pathlib import Path

from marsdog_vision_interaction.utils.config_loader import load_config


def _write_config(path: Path) -> None:
    path.write_text(
        "model: ${MARSDOG_VISION_MODEL_DIR}/model.task\n"
        "data: ${MARSDOG_VISION_DATA_DIR}/faces\n",
        encoding="utf-8",
    )


def test_path_variables_honor_environment_overrides(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "vision.yaml"
    _write_config(config_path)
    model_dir = tmp_path / "external-models"
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("MARSDOG_VISION_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("MARSDOG_VISION_DATA_DIR", str(data_dir))

    config = load_config(config_path)

    assert config["model"] == str(model_dir / "model.task")
    assert config["data"] == str(data_dir / "faces")


def test_path_variables_default_to_checkout_directories(tmp_path, monkeypatch) -> None:
    checkout = tmp_path / "checkout"
    project_dir = checkout / "modules/vision"
    config_dir = project_dir / "config"
    package_dir = project_dir / "marsdog_vision_interaction"
    model_dir = checkout / "models" / "vision"
    config_dir.mkdir(parents=True)
    package_dir.mkdir()
    (checkout / "platform").mkdir()
    (checkout / "platform/modules.json").write_text("{}")
    (project_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
    config_path = config_dir / "vision.yaml"
    _write_config(config_path)
    for name in (
        "MARSDOG_MODEL_DIR",
        "MARSDOG_VISION_PROJECT_DIR",
        "MARSDOG_VISION_MODEL_DIR",
        "MARSDOG_VISION_DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    config = load_config(config_path)

    assert config["model"] == str(model_dir / "model.task")
    assert config["data"] == str(project_dir / "data" / "faces")


def test_debug_osd_uses_compatibility_defaults_when_omitted(tmp_path) -> None:
    config_path = tmp_path / "vision.yaml"
    config_path.write_text("providers: {}\n", encoding="utf-8")

    config = load_config(config_path)

    assert config["debug_osd"] == {
        "enabled": True,
        "show_all_detections": False,
    }


def test_debug_osd_normalizes_explicit_values(tmp_path) -> None:
    config_path = tmp_path / "vision.yaml"
    config_path.write_text(
        "debug_osd:\n"
        "  enabled: false\n"
        "  show_all_detections: true\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["debug_osd"] == {
        "enabled": False,
        "show_all_detections": True,
    }


def test_unified_root_and_specific_vision_override(tmp_path, monkeypatch):
    config_path = tmp_path / "vision.yaml"
    config_path.write_text(
        "model: ${MARSDOG_VISION_MODEL_DIR}/model.task\n"
        "shared: ${MARSDOG_MODEL_DIR}/vision/shared.task\n"
    )
    monkeypatch.delenv("MARSDOG_VISION_MODEL_DIR", raising=False)
    monkeypatch.setenv("MARSDOG_MODEL_DIR", str(tmp_path / "external"))
    config = load_config(config_path)
    assert config["model"] == str(tmp_path / "external/vision/model.task")
    assert config["shared"] == str(tmp_path / "external/vision/shared.task")
    monkeypatch.setenv("MARSDOG_VISION_MODEL_DIR", str(tmp_path / "isolated"))
    config = load_config(config_path)
    assert config["model"] == str(tmp_path / "isolated/model.task")
    assert config["shared"] == str(tmp_path / "external/vision/shared.task")


def test_detached_config_with_explicit_paths_needs_no_root(tmp_path, monkeypatch):
    from marsdog_vision_interaction.utils import model_paths
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    monkeypatch.setattr(model_paths, "__file__", str(tmp_path / "site-packages/pkg/model_paths.py"))
    config_path = tmp_path / "vision.yaml"
    config_path.write_text("model: /srv/weights/model.task\n")
    assert load_config(config_path)["model"] == "/srv/weights/model.task"
