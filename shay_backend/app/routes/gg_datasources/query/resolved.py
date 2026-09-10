"""
GET /resolved — all active datasources visible at the given scope using
top-down inheritance: workspace -> channel -> thread -> message.
"""

from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import ResolvedDatasourcesResponse
from ..response import _to_response

router = APIRouter()


@router.get("/resolved", response_model=ResolvedDatasourcesResponse)
async def get_resolved_datasources(
    request: Request,
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ResolvedDatasourcesResponse:
    """
    Return all active datasources visible at the given scope using
    top-down inheritance:  workspace → channel → thread → message.
    """
    await get_current_user_required(request, db)

    result: ResolvedDatasourcesResponse = ResolvedDatasourcesResponse()

    async def _fetch(level: str, fk_col, fk_val: Optional[str]) -> List[Any]:
        if not fk_val:
            return []
        stmt = (
            select(GGDatasource)
            .where(and_(
                fk_col == UUID(fk_val),
                GGDatasource.level == level,
                GGDatasource.is_active == True,
            ))
            .order_by(GGDatasource.name)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_to_response(r) for r in rows]

    result.workspace = await _fetch("workspace", GGDatasource.workspace_id, workspace_id)
    result.channel   = await _fetch("channel",   GGDatasource.channel_id,   channel_id)
    result.thread    = await _fetch("thread",     GGDatasource.thread_id,    thread_id)
    result.message   = await _fetch("message",    GGDatasource.message_id,   message_id)
    result.total = (
        len(result.workspace) + len(result.channel) +
        len(result.thread)    + len(result.message)
    )
    return result
