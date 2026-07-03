"""Regression tests for list-like settings that are sourced from environment variables."""

from __future__ import annotations

import importlib
import os
import sys


def _reload_config():
    module_name = "app.core.config"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_allowed_origins_accepts_comma_separated_env(monkeypatch):
    """Comma-separated CORS origins should not crash settings initialization."""
    monkeypatch.setenv("SSO_STATE_SECRET", "test-sso-secret")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://app.accsell.ai, https://alb.accsell.ai/",
    )
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com, *.example.com")

    config_module = _reload_config()

    assert config_module.settings.ALLOWED_ORIGINS == [
        "https://app.accsell.ai",
        "https://alb.accsell.ai",
    ]
    assert config_module.settings.ALLOWED_HOSTS == [
        "example.com",
        "*.example.com",
    ]


def test_allowed_origins_accepts_json_array_env(monkeypatch):
    """JSON-array CORS origins should continue to work."""
    monkeypatch.setenv("SSO_STATE_SECRET", "test-sso-secret")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        '["https://app.accsell.ai", "https://alb.accsell.ai/"]',
    )

    config_module = _reload_config()

    assert config_module.settings.ALLOWED_ORIGINS == [
        "https://app.accsell.ai",
        "https://alb.accsell.ai",
    ]

