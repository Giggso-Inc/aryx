"""
GET /resolved  get_resolved_connection

Must stay registered before detail.py's dynamic GET /{connection_id} — a
static single-segment path would otherwise be swallowed by it.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.utils.gg_app_connections import resolve_gg_app_connection

router = APIRouter()


@router.get("/resolved")
async def get_resolved_connection(
    app_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> dict:
    """
    Returns the most specific active GGAppConnection for the given scope + app_key.
    Resolution order: thread → channel → workspace (most specific wins).
    """
    await get_current_user_required(request, db)

    def _to_uuid(v: Optional[str], name: str) -> Optional[UUID]:
        if v is None:
            return None
        try:
            return UUID(v)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid {name} format")

    conn = await resolve_gg_app_connection(
        db,
        app_key,
        thread_id=_to_uuid(thread_id, "thread_id"),
        channel_id=_to_uuid(channel_id, "channel_id"),
        workspace_id=_to_uuid(workspace_id, "workspace_id"),
    )
    if not conn:
        raise HTTPException(
            status_code=404,
            detail="No active app connection found for this scope and app_key",
        )
    return conn.to_dict()
