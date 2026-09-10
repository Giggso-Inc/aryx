"""Aryx bridge: the /workspaces/{workspace_id}/ask endpoint.

Split out of the original app/routes/aryx.py — see app/routes/aryx/__init__.py
for the full module-level docstring describing the bridge architecture.
"""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routes.aryx._shared import _TIMEOUT_ASK, _raise_for_bridge_error, _require_workspace_access
from app.routes.workspaces import _aryx_headers
from app.schemas.aryx import AryxAskRequest

router = APIRouter()


@router.post("/workspaces/{workspace_id}/ask")
async def ask(
    workspace_id: str,
    body: AryxAskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask a question against the tenant's Aryx knowledge graph.

    Request:  {"thread_id": "shay-thread-abc", "question": "..."}
    Response: Aryx's POST /admin/shay/chats/ask body verbatim — see
              AryxAskResponse for the exact shape (answer, terms,
              tools_called, usage, grounding, citations).
    """
    await _require_workspace_access(request, db, workspace_id)

    async with httpx.AsyncClient(timeout=_TIMEOUT_ASK) as client:
        try:
            resp = await client.post(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/chats/ask",
                json={
                    "shay_workspace_id": workspace_id,
                    "shay_thread_id": body.thread_id,
                    "question": body.question,
                },
                headers=_aryx_headers(),
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "ask")
    return resp.json()
