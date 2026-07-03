import base64
import importlib
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reload_config():
    module_name = "app.core.config"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def test_ml_api_key_accepts_plain_text(monkeypatch):
    monkeypatch.setenv("ML_API_KEY", "plain-text-token")

    config_module = _reload_config()

    assert config_module.settings.ML_API_KEY == "plain-text-token"


def test_ml_api_key_decodes_base64(monkeypatch):
    monkeypatch.setenv("ML_API_KEY", base64.b64encode(b"decoded-token").decode("utf-8"))

    config_module = _reload_config()

    assert config_module.settings.ML_API_KEY == "decoded-token"
