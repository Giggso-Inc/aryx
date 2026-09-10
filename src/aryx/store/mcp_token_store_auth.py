"""Verify/authenticate operations for the MCP bearer-token store.

Split out of `store/mcp_token_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep (only `issue()` is patch-tested).
"""
from __future__ import annotations

from aryx.mcp.auth import McpPrincipal
from aryx.queries import load
from aryx.store.mcp_token_store_helpers import _decode_tools, _hash


class _McpTokenAuthMixin:
    """verify / authenticate, mixed into McpTokenStore."""

    def verify(self, token: str) -> bool:
        """Return True if the token exists, is not revoked, and touches it."""
        return self.authenticate(token) is not None

    def authenticate(self, token: str) -> McpPrincipal | None:
        """Return the non-expired token principal and update last-used time."""
        h = _hash(token)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("check_mcp_token"), (h,))
                row = cur.fetchone()
                if row is not None:
                    cur.execute(load("touch_mcp_token"), (h,))
        if row is None:
            return None
        return McpPrincipal(
            token_id=int(row[0]),
            purpose=str(row[1] or "general"),
            allowed_tools=_decode_tools(row[2]),
            workspace_id=int(row[3]) if row[3] is not None else None,
            shay_workspace_id=str(row[4]) if row[4] is not None else None,
            expires_at=row[5],
        )
