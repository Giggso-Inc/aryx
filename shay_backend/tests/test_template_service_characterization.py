"""
Golden-master / characterization tests for app/services/template_service.py.

Purpose: this file had ZERO dedicated test coverage before this pass. It is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we capture
the CURRENT observable behavior of every public method so the split can be
verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real DB, AsyncMock
for the session, `asyncio.run()` instead of pytest-asyncio (no async plugin
installed), and `unittest.mock.patch` at the exact import path used inside
the module under test.

Do not modify app/services/template_service.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


MODPATH = "app.services.template_service"


class _FakeResult:
    def __init__(self, scalar_one_or_none=None):
        self._son = scalar_one_or_none

    def scalar_one_or_none(self):
        return self._son


def _svc(template_dir):
    from app.services.template_service import TemplateService
    with patch(f"{MODPATH}.settings") as mock_settings:
        mock_settings.TEMPLATE_DIR = template_dir
        return TemplateService()


# ---------------------------------------------------------------------------
# get_template_content
# ---------------------------------------------------------------------------

def test_get_template_content_not_found_raises_404():
    svc = _svc("/tmp")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.get_template_content("tmpl-1", db))
    assert exc_info.value.status_code == 404
    assert "Template not found" in exc_info.value.detail


def test_get_template_content_file_missing_raises_404(tmp_path):
    svc = _svc(str(tmp_path))
    db = AsyncMock()
    template = MagicMock(
        template_id="tmpl-1", template_name="missing.html",
        file_path=None, additional_config=None,
    )
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=template))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.get_template_content("tmpl-1", db))
    assert exc_info.value.status_code == 404
    assert "Template file not found" in exc_info.value.detail


def test_get_template_content_path_outside_template_dir_raises_403(tmp_path):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "evil.html"
    outside_file.write_text("evil content")

    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    svc = _svc(str(template_dir))
    db = AsyncMock()
    template = MagicMock(
        template_id="tmpl-1", template_name="evil.html",
        file_path=str(outside_file), additional_config=None,
    )
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=template))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.get_template_content("tmpl-1", db))
    assert exc_info.value.status_code == 403
    assert "outside template directory" in exc_info.value.detail


def test_get_template_content_success_with_explicit_file_path(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    tmpl_file = template_dir / "welcome.html"
    tmpl_file.write_text("Hello {name}")

    svc = _svc(str(template_dir))
    db = AsyncMock()
    template = MagicMock(
        template_id="tmpl-1", template_name="welcome.html",
        file_path=str(tmpl_file), additional_config={"foo": "bar"},
    )
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=template))

    result = asyncio.run(svc.get_template_content("tmpl-1", db))

    assert result == {
        "template_id": "tmpl-1",
        "template_name": "welcome.html",
        "content": "Hello {name}",
        "file_path": str(tmpl_file),
        "additional_config": {"foo": "bar"},
    }


def test_get_template_content_falls_back_to_template_dir_when_no_file_path(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    tmpl_file = template_dir / "fallback.html"
    tmpl_file.write_text("Fallback content")

    svc = _svc(str(template_dir))
    db = AsyncMock()
    template = MagicMock(
        template_id="tmpl-2", template_name="fallback.html",
        file_path=None, additional_config=None,
    )
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=template))

    result = asyncio.run(svc.get_template_content("tmpl-2", db))

    assert result["content"] == "Fallback content"
    assert result["additional_config"] == {}


def test_get_template_content_db_error_wraps_as_500():
    svc = _svc("/tmp")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.get_template_content("tmpl-1", db))
    assert exc_info.value.status_code == 500
    assert "Error fetching template content" in exc_info.value.detail


# ---------------------------------------------------------------------------
# process_template_content
# ---------------------------------------------------------------------------

def test_process_template_content_substitutes_variables():
    svc = _svc("/tmp")
    result = svc.process_template_content(
        "Hello {name}, welcome to {company}!",
        {"name": "Jane", "company": "Acme"},
    )
    assert result == "Hello Jane, welcome to Acme!"


def test_process_template_content_leaves_css_braces_untouched_when_not_a_key():
    svc = _svc("/tmp")
    result = svc.process_template_content(
        "body { color: red; } Hello {name}",
        {"name": "Jane"},
    )
    assert result == "body { color: red; } Hello Jane"


def test_process_template_content_missing_variable_leaves_placeholder():
    svc = _svc("/tmp")
    result = svc.process_template_content("Hello {name}", {})
    assert result == "Hello {name}"


# ---------------------------------------------------------------------------
# get_default_invitation_template
# ---------------------------------------------------------------------------

def test_get_default_invitation_template_contains_expected_placeholders():
    svc = _svc("/tmp")
    template = svc.get_default_invitation_template()
    assert "{platform_name}" in template
    assert "{company_name}" in template
    assert "{user_name}" in template
    assert "{invited_by}" in template
    assert "{registration_short_link}" in template
    assert "{expires_at}" in template
    assert "{current_year}" in template
    assert template.strip().startswith("<!DOCTYPE html>")


def test_get_default_invitation_template_is_processable():
    svc = _svc("/tmp")
    template = svc.get_default_invitation_template()
    processed = svc.process_template_content(template, {
        "platform_name": "Aryx",
        "company_name": "Acme",
        "user_name": "Jane",
        "invited_by": "Bob",
        "registration_short_link": "https://short.link/abc",
        "expires_at": "2026-01-01",
        "current_year": "2026",
    })
    assert "{platform_name}" not in processed
    assert "Aryx" in processed
    assert "Acme" in processed
