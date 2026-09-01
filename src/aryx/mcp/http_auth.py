"""Shared bearer authentication for Aryx MCP HTTP transports."""

from __future__ import annotations

import logging
import os

from aryx.mcp.auth import McpPrincipal

logger = logging.getLogger(__name__)


def authenticate_authorization_header(value: str) -> McpPrincipal | None:
    """Authenticate one Authorization header, failing closed on any error."""
    auth = (value or "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        if os.environ.get("ARYX_MCP_AUTH_OPTIONAL", "1") == "1":
            return McpPrincipal()
        return None
    try:
        from aryx.config import get_settings
        from aryx.store.mcp_token_store import McpTokenStore

        return McpTokenStore(get_settings().effective_dsn()).authenticate(token)
    except Exception as exc:  # noqa: BLE001
        logger.error("mcp auth check failed — failing closed: %s", exc)
        return None
