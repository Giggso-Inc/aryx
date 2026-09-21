"""sales_streamlit/app.py's workspace sidebar selectbox previously listed
every workspace ARYX_SALES_WORKSPACES configured, with no check that the
logged-in rep (resolve_actor_id()) actually belongs to the one they picked
-- the sales_cpq token itself is workspace-scoped, but nothing above it
gated which token a given human could reach. A rep authenticated for
Workspace A could select Workspace B in the dropdown and act there.

_allowed_labels_for_actor() closes this by filtering to only the labels
ARYX_SALES_WORKSPACE_MEMBERS lists the actor's (hashed) email under.
"""
from __future__ import annotations

import hashlib

import pytest

from sales_streamlit.app import _allowed_labels_for_actor


def _sso(email: str) -> str:
    return f"sso:{hashlib.sha256(email.casefold().encode('utf-8')).hexdigest()}"


WORKSPACES = {"Acme": "tok-acme", "Globex": "tok-globex"}


def test_single_workspace_deployment_needs_no_membership_config(monkeypatch) -> None:
    monkeypatch.delenv("ARYX_SALES_WORKSPACE_MEMBERS", raising=False)
    assert _allowed_labels_for_actor(_sso("anyone@example.com"), {"Default": "tok"}) == ["Default"]


def test_multi_workspace_without_membership_config_refuses_to_expose_everything(monkeypatch) -> None:
    monkeypatch.delenv("ARYX_SALES_WORKSPACE_MEMBERS", raising=False)
    with pytest.raises(RuntimeError, match="ARYX_SALES_WORKSPACE_MEMBERS"):
        _allowed_labels_for_actor(_sso("anyone@example.com"), WORKSPACES)


def test_actor_only_sees_their_own_workspace(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARYX_SALES_WORKSPACE_MEMBERS",
        '{"Acme": ["rep-a@acme.com"], "Globex": ["rep-g@globex.com"]}',
    )
    assert _allowed_labels_for_actor(_sso("rep-a@acme.com"), WORKSPACES) == ["Acme"]


def test_email_matching_is_case_insensitive(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARYX_SALES_WORKSPACE_MEMBERS",
        '{"Acme": ["Rep-A@Acme.com"], "Globex": []}',
    )
    assert _allowed_labels_for_actor(_sso("rep-a@acme.com"), WORKSPACES) == ["Acme"]


def test_actor_who_belongs_to_multiple_workspaces_sees_all_of_them(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARYX_SALES_WORKSPACE_MEMBERS",
        '{"Acme": ["rep@msi.com"], "Globex": ["rep@msi.com"]}',
    )
    assert _allowed_labels_for_actor(_sso("rep@msi.com"), WORKSPACES) == ["Acme", "Globex"]


def test_actor_not_in_any_list_sees_nothing() -> None:
    import json
    import os

    os.environ["ARYX_SALES_WORKSPACE_MEMBERS"] = json.dumps(
        {"Acme": ["rep-a@acme.com"], "Globex": ["rep-g@globex.com"]}
    )
    try:
        assert _allowed_labels_for_actor(_sso("outsider@evil.com"), WORKSPACES) == []
    finally:
        del os.environ["ARYX_SALES_WORKSPACE_MEMBERS"]


def test_anonymous_session_actor_denied_by_default(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARYX_SALES_WORKSPACE_MEMBERS",
        '{"Acme": ["rep-a@acme.com"], "Globex": []}',
    )
    assert _allowed_labels_for_actor("session:some-uuid", WORKSPACES) == []


def test_anonymous_session_actor_allowed_only_with_explicit_wildcard(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARYX_SALES_WORKSPACE_MEMBERS",
        '{"Acme": ["*"], "Globex": ["rep-g@globex.com"]}',
    )
    assert _allowed_labels_for_actor("session:some-uuid", WORKSPACES) == ["Acme"]


def test_invalid_json_raises_clear_error(monkeypatch) -> None:
    monkeypatch.setenv("ARYX_SALES_WORKSPACE_MEMBERS", "not json")
    with pytest.raises(RuntimeError, match="valid JSON"):
        _allowed_labels_for_actor(_sso("rep-a@acme.com"), WORKSPACES)
