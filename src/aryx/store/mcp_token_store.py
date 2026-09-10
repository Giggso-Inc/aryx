"""MCP bearer-token store — issue, list, verify, revoke.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`mcp_token_store_helpers.py` (`_hash`/`_decode_tools`),
`mcp_token_store_admin.py` (`_McpTokenAdminMixin`: rescope/list_/revoke),
and `mcp_token_store_auth.py` (`_McpTokenAuthMixin`: verify/authenticate),
all mixed into `McpTokenStore` here. Only `issue()` is directly
whitebox-patch-tested (`aryx.store.mcp_token_store.get_settings`/`load`,
scoped locally within each test's own `with patch(...)` block, in
`tests/test_mcp_token_store_oracle_issue.py`) — confirmed via grep that
no other method carries any patch risk, so `issue` stays here while
everything else moved out.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

from aryx.config import get_settings
from aryx.mcp.auth import SALES_CPQ_PURPOSE, SALES_CPQ_TOOLS
from aryx.queries import load
from aryx.store.mcp_token_store_admin import _McpTokenAdminMixin
from aryx.store.mcp_token_store_auth import _McpTokenAuthMixin
from aryx.store.mcp_token_store_helpers import _FULL_SALES_SCOPE_SENTINEL, _decode_tools, _hash
from aryx.store.pool import get_pool

__all__ = ["McpTokenStore"]

logger = logging.getLogger(__name__)


class McpTokenStore(_McpTokenAdminMixin, _McpTokenAuthMixin):
    """CRUD for aryx_mcp_token."""

    def __init__(self, dsn: str) -> None:
        """Acquire the shared connection pool for this DSN."""
        self._pool = get_pool(dsn)

    def issue(
        self,
        label: str,
        *,
        purpose: str = "general",
        allowed_tools: set[str] | frozenset[str] | None = None,
        workspace_id: int | None = None,
        shay_workspace_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Generate a new token. Returns plain token ONCE — never again."""
        purpose = (purpose or "general").strip().lower()
        if purpose not in {"general", SALES_CPQ_PURPOSE}:
            raise ValueError("MCP token purpose must be general or sales_cpq")
        explicit_tools = frozenset(allowed_tools or ())
        encoded_tools = ""
        if purpose == SALES_CPQ_PURPOSE:
            if explicit_tools:
                unknown = explicit_tools - SALES_CPQ_TOOLS
                if unknown:
                    raise ValueError(
                        "sales_cpq tokens may only allow the sales chat tools"
                    )
                encoded_tools = ",".join(sorted(explicit_tools))
            else:
                # No explicit restriction requested -- grant every current
                # AND future sales_cpq tool (see _decode_tools) instead of
                # baking in today's SALES_CPQ_TOOLS snapshot, so this
                # token never needs reissuing (or its client-side key
                # rotated) just because a new sales_chat_* tool ships.
                encoded_tools = _FULL_SALES_SCOPE_SENTINEL
            if not workspace_id or not shay_workspace_id:
                raise ValueError(
                    "sales_cpq tokens require workspace_id and shay_workspace_id"
                )
        elif explicit_tools:
            raise ValueError("allowed_tools is only supported for sales_cpq tokens")

        raw = "aryx_" + secrets.token_urlsafe(32)
        prefix = raw[:12]
        insert_params = (
            label, _hash(raw), prefix, purpose, encoded_tools,
            workspace_id, shay_workspace_id, expires_at,
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("insert_mcp_token"), insert_params)
                if get_settings().effective_db_backend() == "oci":
                    # No RETURNING on Oracle (see insert_mcp_token.sql's
                    # override note) -- prefix is already unique (derived
                    # from a fresh secrets.token_urlsafe() call above), so
                    # it's a safe follow-up lookup key.
                    cur.execute(load("select_mcp_token_by_prefix"), (prefix,))
                row = cur.fetchone()
        logger.info("mcp token issued id=%s label=%s", row[0], label)
        return {
            "id": row[0],
            "label": row[1],
            "prefix": row[2],
            "created_at": row[3],
            "purpose": row[4],
            "allowed_tools": sorted(_decode_tools(row[5])),
            "workspace_id": row[6],
            "shay_workspace_id": row[7],
            "expires_at": row[8],
            "token": raw,
        }

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""
