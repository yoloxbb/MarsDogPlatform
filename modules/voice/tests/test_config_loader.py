from __future__ import annotations

from pathlib import Path

from marsdog_voice_interaction.utils.config_loader import load_config


def test_load_config_resolves_declared_paths_from_yaml_directory(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "voice.yaml"
    config_path.write_text(
        """
logging:
  dir: ../log
audio_debug:
  output_dir: ../debug_audio
storage:
  root: ../data
command_lexicon:
  catalog: command_catalog.yaml
object_target_routing:
  catalog: object_targets.yaml
providers:
  audio:
    config:
      vad_model: ../../models/vad.onnx
  kws:
    config:
      keywords_file: keywords.txt
  wakeup:
    config:
      port: /dev/ttyACM0
topics:
  audio_event: /perception/audio_event
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["logging"]["dir"] == str(tmp_path / "log")
    assert config["audio_debug"]["output_dir"] == str(
        tmp_path / "debug_audio"
    )
    assert config["storage"]["root"] == str(tmp_path / "data")
    assert config["command_lexicon"]["catalog"] == str(
        config_dir / "command_catalog.yaml"
    )
    assert config["object_target_routing"]["catalog"] == str(
        config_dir / "object_targets.yaml"
    )
    assert config["providers"]["audio"]["config"]["vad_model"] == str(
        tmp_path.parent / "models" / "vad.onnx"
    )
    assert config["providers"]["kws"]["config"]["keywords_file"] == str(
        config_dir / "keywords.txt"
    )
    assert config["providers"]["wakeup"]["config"]["port"] == "/dev/ttyACM0"
    assert config["topics"]["audio_event"] == "/perception/audio_event"


def test_project_configs_use_portable_filesystem_paths(monkeypatch) -> None:
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    root = Path(__file__).parents[1]
    production_text = (root / "config" / "voice.yaml").read_text(
        encoding="utf-8"
    )
    production = load_config(root / "config" / "voice.yaml")
    event_mock = load_config(root / "config" / "voice.mock.yaml")
    pipeline_mock = load_config(root / "config" / "voice.pipeline.mock.yaml")

    assert "/home/cat/" not in production_text
    assert production["command_lexicon"] == {
        "enabled": True,
        "catalog": str(root / "config" / "command_catalog.yaml"),
        # Homophone fallback for ASR near-miss characters; on by default so
        # short commands still resolve when ASR writes the wrong character.
        "fuzzy_matching": True,
    }
    assert event_mock["storage"]["root"] == str(root / "data" / "mock")
    assert pipeline_mock["storage"]["root"] == str(
        root / "data" / "pipeline_mock"
    )


def test_production_models_use_platform_root_from_foreign_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("MARSDOG_MODEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    source = Path(__file__).resolve().parents[1]
    config = load_config(source / "config/voice.yaml")
    model_root = source.parents[1] / "models"
    for provider, field, relative in (
        ("audio", "vad_model", "vad/silero_vad.onnx"),
        ("kws", "model_dir", "wakeup/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"),
        ("asr", "asr_model", "asr/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/model.int8.onnx"),
        ("asr", "tokens", "asr/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/tokens.txt"),
        ("speaker", "speaker_model", "speaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"),
        ("intent_llm", "model", "llm/qwen2_5_5b_rk3588_260903_w8a8.rkllm"),
    ):
        assert config["providers"][provider]["config"][field] == str(model_root / relative)


def test_model_root_expansion_preserves_explicit_paths_and_non_model_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSDOG_MODEL_DIR", str(tmp_path / "external models"))
    config_path = tmp_path / "voice.yaml"
    absolute_model = tmp_path / "custom.onnx"
    config_path.write_text(
        "providers:\n"
        "  audio:\n    config:\n      vad_model: ${MARSDOG_MODEL_DIR}/vad/vad.onnx\n"
        f"  asr:\n    config:\n      asr_model: {absolute_model}\n"
        "  intent_llm:\n    config:\n      lib_path: lib/librkllmrt.so\n"
        "storage:\n  root: data\n"
    )
    config = load_config(config_path)
    assert config["providers"]["audio"]["config"]["vad_model"] == str(tmp_path / "external models/vad/vad.onnx")
    assert config["providers"]["asr"]["config"]["asr_model"] == str(absolute_model)
    assert config["providers"]["intent_llm"]["config"]["lib_path"] == str(tmp_path / "lib/librkllmrt.so")
    assert config["storage"]["root"] == str(tmp_path / "data")
