"""Token hashing + allowed-tools decoding for the MCP bearer-token store.

Split out of `store/mcp_token_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import hashlib
from typing import Any

from aryx.mcp.auth import SALES_CPQ_TOOLS

# Stored in the allowed_tools column instead of a literal comma-joined list
# when a sales_cpq token is issued (or rescoped) with no explicit
# restriction. Resolved live against SALES_CPQ_TOOLS on every decode --
# never frozen at issuance -- so a fully-scoped token automatically covers
# any sales_chat_* tool added after it was issued/rescoped, and never
# needs to be reissued (or its client-side key rotated) just because a
# new tool shipped. An explicit, literal subset (an admin deliberately
# narrowing a token) is decoded as-is and never auto-expands.
_FULL_SALES_SCOPE_SENTINEL = "*"


def _hash(token: str) -> str:
    """SHA-256 of the raw token (storage form)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _decode_tools(value: Any) -> frozenset[str]:
    """Decode the portable comma-separated allowed-tools database field.

    "*" is the full-scope sentinel (see _FULL_SALES_SCOPE_SENTINEL) --
    resolved live against the CURRENT SALES_CPQ_TOOLS on every call, not
    frozen at issuance time.
    """
    if not value:
        return frozenset()
    if value == _FULL_SALES_SCOPE_SENTINEL:
        return SALES_CPQ_TOOLS
    return frozenset(part.strip() for part in str(value).split(",") if part.strip())
