"""Library selection is shared and cannot change beneath live models."""
from __future__ import annotations

import sys
import logging
from types import ModuleType, SimpleNamespace

import pytest

from marsdog_vision_interaction.utils.rknn_runtime import configure_rknn_runtime


def install_runtime_stub(monkeypatch, tmp_path):
    package = ModuleType('rknnlite')
    package.__file__ = str(tmp_path/'rknnlite/__init__.py')
    api = ModuleType('rknnlite.api')
    base = type('RKNNRuntime', (), {})
    lite = SimpleNamespace(RKNNRuntime=base)
    api.rknn_lite = lite
    runtime = ModuleType('rknnlite.api.rknn_runtime')
    runtime.RKNNRuntime = base
    monkeypatch.setitem(sys.modules, 'rknnlite', package)
    monkeypatch.setitem(sys.modules, 'rknnlite.api', api)
    monkeypatch.setitem(sys.modules, 'rknnlite.api.rknn_runtime', runtime)
    return lite


def test_runtime_selection_is_idempotent_and_rejects_conflict(monkeypatch, tmp_path):
    lite = install_runtime_stub(monkeypatch, tmp_path)
    a, b = tmp_path/'one.so', tmp_path/'two.so'
    a.touch()
    b.touch()
    configure_rknn_runtime(str(a))
    selected = lite.RKNNRuntime
    assert selected()._get_rknn_api_lib_path() == str(a.resolve())
    configure_rknn_runtime(str(a))
    assert lite.RKNNRuntime is selected
    with pytest.raises(RuntimeError, match='cannot switch'):
        configure_rknn_runtime(str(b))
    assert lite.RKNNRuntime is selected


def test_runtime_explicit_path_precedes_environment(monkeypatch, tmp_path):
    lite = install_runtime_stub(monkeypatch, tmp_path)
    explicit, environment = tmp_path/'explicit.so', tmp_path/'environment.so'
    explicit.touch()
    environment.touch()
    monkeypatch.setenv('MARSDOG_RKNN_RUNTIME_LIBRARY', str(environment))
    configure_rknn_runtime(str(explicit))
    assert lite.RKNNRuntime._marsdog_runtime_library == str(explicit)


def test_runtime_environment_path_precedes_package(monkeypatch, tmp_path):
    lite = install_runtime_stub(monkeypatch, tmp_path)
    environment = tmp_path/'environment.so'
    environment.touch()
    monkeypatch.setenv('MARSDOG_RKNN_RUNTIME_LIBRARY', str(environment))
    configure_rknn_runtime()
    assert lite.RKNNRuntime._marsdog_runtime_library == str(environment)


def test_runtime_restores_standard_logging_names(monkeypatch, tmp_path):
    original_names = dict(logging._nameToLevel)
    original_reverse = dict(logging._levelToName)
    try:
        # This is the state observed after rknnlite.api's import-time logging
        # bootstrap on toolkit-lite2 2.3.2.
        logging._nameToLevel.clear()
        logging._levelToName.clear()
        lite = install_runtime_stub(monkeypatch, tmp_path)
        runtime_library = tmp_path / "runtime.so"
        runtime_library.touch()
        configure_rknn_runtime(str(runtime_library))
        for name, value in (
            ("WARNING", logging.WARNING),
            ("WARN", logging.WARN),
            ("ERROR", logging.ERROR),
            ("INFO", logging.INFO),
        ):
            assert logging._checkLevel(name) == value
        assert lite.RKNNRuntime._marsdog_runtime_library == str(runtime_library.resolve())
    finally:
        logging._nameToLevel.clear()
        logging._nameToLevel.update(original_names)
        logging._levelToName.clear()
        logging._levelToName.update(original_reverse)
