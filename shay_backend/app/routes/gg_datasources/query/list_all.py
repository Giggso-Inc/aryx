"""GET / — list datasources with filters + pagination."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceList
from ..response import _to_response

router = APIRouter()


@router.get("/", response_model=GGDatasourceList)
async def list_datasources(
    request: Request,
    level:             Optional[str]  = Query(None, description="workspace | channel | thread | message"),
    workspace_id:      Optional[str]  = Query(None),
    channel_id:        Optional[str]  = Query(None),
    thread_id:         Optional[str]  = Query(None),
    message_id:        Optional[str]  = Query(None),
    storage_type:      Optional[str]  = Query(None),
    processing_status: Optional[str]  = Query(None),
    embedding_status:  Optional[int]  = Query(None),
    is_active:         Optional[bool] = Query(None),
    page:              int = Query(1, ge=1),
    page_size:         int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceList:
    """List datasources with optional filters and pagination."""
    await get_current_user_required(request, db)

    filters = []
    if level:             filters.append(GGDatasource.level == level)
    if workspace_id:      filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:        filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:         filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:        filters.append(GGDatasource.message_id   == UUID(message_id))
    if storage_type:      filters.append(GGDatasource.storage_type == storage_type)
    if processing_status: filters.append(GGDatasource.processing_status == processing_status)
    if embedding_status is not None:
                          filters.append(GGDatasource.embedding_status == embedding_status)
    if is_active is not None:
                          filters.append(GGDatasource.is_active == is_active)

    count_stmt = select(func.count(GGDatasource.id)).where(and_(*filters)) if filters else select(func.count(GGDatasource.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        select(GGDatasource)
        .where(and_(*filters) if filters else True)
        .order_by(GGDatasource.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return GGDatasourceList(
        items=[_to_response(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
