"""MCP bearer-token CRUD — issue, list, revoke. Plain token shown ONCE."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.mcp.auth import SALES_CPQ_PURPOSE, SALES_CPQ_TOOLS
from aryx.store.mcp_token_store import McpTokenStore

logger = logging.getLogger(__name__)


class TokenRequest(BaseModel):
    """Token issuance request."""

    label: str = ""
    purpose: Literal["general", "sales_cpq"] = "general"
    allowed_tools: list[str] = Field(default_factory=list)
    workspace_id: int | None = None
    shay_workspace_id: str | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "TokenRequest":
        """Require a complete, non-escalating sales integration scope."""
        purpose = self.purpose.strip().lower()
        if purpose == SALES_CPQ_PURPOSE:
            if not self.workspace_id or not self.shay_workspace_id:
                raise ValueError(
                    "sales_cpq tokens require workspace_id and shay_workspace_id"
                )
            unknown = set(self.allowed_tools) - SALES_CPQ_TOOLS
            if unknown:
                raise ValueError(
                    "sales_cpq tokens may only allow the sales chat tools"
                )
        elif self.allowed_tools:
            raise ValueError("allowed_tools is only supported for sales_cpq tokens")
        self.purpose = purpose
        return self


def mcp_tokens_router() -> APIRouter:
    """Build the /admin/mcp/tokens router."""
    router = APIRouter(
        prefix="/admin/mcp/tokens",
        dependencies=[Depends(require_api_key)],
    )

    @router.get("")
    def list_tokens() -> list[dict[str, Any]]:
        """Return all tokens (metadata only, no raw token)."""
        store = McpTokenStore(get_settings().rdb_dsn)
        try:
            return store.list_()
        finally:
            store.close()

    @router.post("")
    def issue_token(req: TokenRequest) -> dict[str, Any]:
        """Issue a new bearer token. Raw token visible ONCE here."""
        settings = get_settings()
        if (
            req.purpose == SALES_CPQ_PURPOSE
            and settings.effective_db_backend() == "oci"
        ):
            raise HTTPException(
                501,
                "Sales CPQ tokens require PostgreSQL-backed Shay threads.",
            )
        store = McpTokenStore(settings.rdb_dsn)
        try:
            return store.issue(
                req.label or "unnamed",
                purpose=req.purpose,
                allowed_tools=set(req.allowed_tools),
                workspace_id=req.workspace_id,
                shay_workspace_id=req.shay_workspace_id,
                expires_at=req.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            store.close()

    @router.delete("/{token_id}")
    def revoke_token(token_id: int) -> dict[str, Any]:
        """Revoke a token by id."""
        store = McpTokenStore(get_settings().rdb_dsn)
        try:
            row = store.revoke(token_id)
            if not row:
                raise HTTPException(404, "token not found or already revoked")
            return {"status": "revoked", **row}
        finally:
            store.close()

    return router
