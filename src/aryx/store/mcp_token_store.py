"""MCP bearer-token store — issue, list, verify, revoke."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any

from aryx.mcp.auth import (
    SALES_CPQ_PURPOSE,
    SALES_CPQ_TOOLS,
    McpPrincipal,
)
from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


def _hash(token: str) -> str:
    """SHA-256 of the raw token (storage form)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class McpTokenStore:
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
        tools = frozenset(allowed_tools or ())
        if purpose == SALES_CPQ_PURPOSE:
            tools = tools or SALES_CPQ_TOOLS
            unknown = tools - SALES_CPQ_TOOLS
            if unknown:
                raise ValueError(
                    "sales_cpq tokens may only allow the sales chat tools"
                )
            if not workspace_id or not shay_workspace_id:
                raise ValueError(
                    "sales_cpq tokens require workspace_id and shay_workspace_id"
                )
        elif tools:
            raise ValueError("allowed_tools is only supported for sales_cpq tokens")

        raw = "aryx_" + secrets.token_urlsafe(32)
        prefix = raw[:12]
        encoded_tools = ",".join(sorted(tools))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("insert_mcp_token"),
                    (
                        label,
                        _hash(raw),
                        prefix,
                        purpose,
                        encoded_tools,
                        workspace_id,
                        shay_workspace_id,
                        expires_at,
                    ),
                )
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

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""


def _decode_tools(value: Any) -> frozenset[str]:
    """Decode the portable comma-separated allowed-tools database field."""
    if not value:
        return frozenset()
    return frozenset(part.strip() for part in str(value).split(",") if part.strip())
