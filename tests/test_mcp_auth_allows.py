"""Tests for McpPrincipal.allows() — sales_chat_* must never fall through
the general-purpose allow-all, even for the default/anonymous principal
that ARYX_MCP_AUTH_OPTIONAL=1 (the default) hands out when no bearer token
is presented at all. See PR #160 review finding M1.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aryx.mcp.auth import McpPrincipal, SALES_CPQ_TOOLS


def _sales_principal(**overrides) -> McpPrincipal:
    defaults = dict(
        token_id=1,
        purpose="sales_cpq",
        allowed_tools=frozenset(SALES_CPQ_TOOLS),
        workspace_id=1,
        shay_workspace_id="ws",
    )
    defaults.update(overrides)
    return McpPrincipal(**defaults)


def test_anonymous_principal_denied_all_sales_chat_tools() -> None:
    anon = McpPrincipal()
    for tool in SALES_CPQ_TOOLS:
        assert anon.allows(tool) is False


def test_anonymous_principal_allowed_general_tools() -> None:
    anon = McpPrincipal()
    assert anon.allows("list") is True
    assert anon.allows("ask") is True
    assert anon.allows("ontology_search") is True


def test_sales_cpq_principal_allowed_all_scoped_tools() -> None:
    principal = _sales_principal()
    for tool in SALES_CPQ_TOOLS:
        assert principal.allows(tool) is True


def test_sales_cpq_principal_denied_general_tools() -> None:
    principal = _sales_principal()
    assert principal.allows("list") is False
    assert principal.allows("ask") is False
    assert principal.allows("ontology_search") is False


def test_sales_cpq_principal_denied_tool_outside_allowed_tools() -> None:
    principal = _sales_principal(allowed_tools=frozenset({"sales_chat_start"}))
    assert principal.allows("sales_chat_start") is True
    assert principal.allows("sales_chat_send") is False


def test_expired_principal_denied_every_tool() -> None:
    expired = _sales_principal(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert expired.allows("sales_chat_start") is False
    anon_expired = McpPrincipal(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert anon_expired.allows("list") is False
