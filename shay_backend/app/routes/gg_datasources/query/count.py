"""GET /count — connected datasource count by storage type."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import DatasourceTypeCount, DatasourceTypeCountResponse

router = APIRouter()


@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    level:        Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
) -> DatasourceTypeCountResponse:
    """Get count of connected datasources by storage type (local, cloud, app, database)."""
    await get_current_user_required(request, db)

    filters = [GGDatasource.is_connected == True]
    if level:        filters.append(GGDatasource.level == level)
    if workspace_id: filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:   filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:    filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:   filters.append(GGDatasource.message_id   == UUID(message_id))

    count_q = (
        select(GGDatasource.storage_type, func.count(GGDatasource.id).label("cnt"))
        .where(and_(*filters))
        .group_by(GGDatasource.storage_type)
    )
    rows = (await db.execute(count_q)).all()
    type_counts = {r.storage_type: r.cnt for r in rows}

    ds_types = ["local", "cloud", "app", "database"]
    counts = []
    total = 0
    for t in ds_types:
        c = type_counts.get(t, 0)
        total += c
        counts.append(DatasourceTypeCount(type=t, count=c))

    return DatasourceTypeCountResponse(counts=counts, total_connected=total)
