"""McpTokenStore — the "*" full-scope sentinel and rescope() in-place update.

Root cause this closes: allowed_tools was previously frozen into the DB row
at issuance time (McpTokenStore.issue: `tools = tools or SALES_CPQ_TOOLS`,
baked in once). Adding a new sales_chat_* tool to SALES_CPQ_TOOLS later
never reached already-issued tokens, forcing a manual reissue (and a
client-side key rotation) every time. The "*" sentinel defers that
resolution to request time instead of issuance time.

These tests exercise _decode_tools and the sentinel/rescope contract
directly, without a real Postgres connection.
"""
from __future__ import annotations

from aryx.mcp.auth import SALES_CPQ_TOOLS
from aryx.store.mcp_token_store import _FULL_SALES_SCOPE_SENTINEL, _decode_tools


def test_decode_tools_empty_value_is_empty_frozenset():
    assert _decode_tools("") == frozenset()
    assert _decode_tools(None) == frozenset()


def test_decode_tools_literal_list_is_decoded_as_is():
    assert _decode_tools("sales_chat_start,sales_chat_send") == frozenset(
        {"sales_chat_start", "sales_chat_send"}
    )


def test_decode_tools_sentinel_resolves_to_current_sales_cpq_tools():
    assert _decode_tools(_FULL_SALES_SCOPE_SENTINEL) == SALES_CPQ_TOOLS


def test_sentinel_is_the_literal_asterisk():
    """Pin the on-the-wire representation -- this is what's stored in the
    database column, so an accidental rename here silently breaks every
    already-issued full-scope token."""
    assert _FULL_SALES_SCOPE_SENTINEL == "*"