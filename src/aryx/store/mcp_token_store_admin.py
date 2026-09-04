"""Admin operations (rescope/list/revoke) for the MCP bearer-token store.

Split out of `store/mcp_token_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep (only `issue()` is patch-tested, in `test_mcp_token_store_oracle_issue.py`).
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.mcp.auth import SALES_CPQ_TOOLS
from aryx.queries import load
from aryx.store.mcp_token_store_helpers import _FULL_SALES_SCOPE_SENTINEL, _decode_tools

logger = logging.getLogger(__name__)


class _McpTokenAdminMixin:
    """rescope / list_ / revoke, mixed into McpTokenStore."""

    def rescope(
        self, token_id: int, allowed_tools: set[str] | frozenset[str] | None,
    ) -> dict[str, Any]:
        """Update an existing, non-revoked sales_cpq token's allowed_tools
        in place -- no new raw token is generated, so the client's
        already-configured key never changes. Pass None/empty to grant
        full current+future sales_cpq scope (the "*" sentinel -- see
        _decode_tools); pass an explicit set to narrow the token to
        exactly those tools.
        """
        tools = frozenset(allowed_tools or ())
        if tools:
            unknown = tools - SALES_CPQ_TOOLS
            if unknown:
                raise ValueError(
                    "sales_cpq tokens may only allow the sales chat tools"
                )
            encoded_tools = ",".join(sorted(tools))
        else:
            encoded_tools = _FULL_SALES_SCOPE_SENTINEL
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_mcp_token_scope"), (encoded_tools, int(token_id)),
                )
                row = cur.fetchone()
        if not row:
            return {}
        logger.info("mcp token rescoped id=%s", row[0])
        return {
            "id": row[0],
            "label": row[1],
            "allowed_tools": sorted(_decode_tools(encoded_tools)),
        }

    def list_(self) -> list[dict[str, Any]]:
        """Return all tokens (no raw token, only prefix + metadata)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_mcp_tokens"))
                rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "label": row[1],
                "prefix": row[2],
                "created_at": row[3],
                "last_used_at": row[4],
                "revoked_at": row[5],
                "purpose": row[6],
                "allowed_tools": sorted(_decode_tools(row[7])),
                "workspace_id": row[8],
                "shay_workspace_id": row[9],
                "expires_at": row[10],
            }
            for row in rows
        ]

    def revoke(self, token_id: int) -> dict[str, Any]:
        """Mark a token revoked. Returns id+label or empty dict if not found."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("revoke_mcp_token"), (int(token_id),))
                row = cur.fetchone()
        if not row:
            return {}
        logger.info("mcp token revoked id=%s", row[0])
        return {"id": row[0], "label": row[1]}
