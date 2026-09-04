"""
Read/list endpoints (must be registered before app.routes.gg_datasources.detail,
whose GET /{datasource_id} would otherwise swallow these literal paths):

  GET    /resolved   inheritance-aware fetch across workspace/channel/thread/message
  GET    /stats      datasource statistics (scope-filtered)
  GET    /count      connected datasource count by storage type
  GET    /           list with filters + pagination
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import (
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    GGDatasourceList,
    GGDatasourceStats,
    ResolvedDatasourcesResponse,
)
from .response import _to_response

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


@router.get("/stats", response_model=GGDatasourceStats)
async def get_datasource_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    level:        Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
) -> GGDatasourceStats:
    """Get datasource statistics, optionally scoped by level and scope ID."""
    await get_current_user_required(request, db)

    filters = []
    if level:        filters.append(GGDatasource.level == level)
    if workspace_id: filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:   filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:    filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:   filters.append(GGDatasource.message_id   == UUID(message_id))

    base_q = select(GGDatasource).where(and_(*filters)) if filters else select(GGDatasource)

    all_rows = (await db.execute(base_q)).scalars().all()
    total     = len(all_rows)
    active    = sum(1 for r in all_rows if r.is_active)
    processed = sum(1 for r in all_rows if r.is_processed)
    pending   = sum(1 for r in all_rows if r.processing_status == "pending")
    failed_c  = sum(1 for r in all_rows if r.processing_status == "failed")
    total_sz  = sum(r.file_size for r in all_rows if r.file_size)

    st_breakdown: Dict[str, int] = {}
    prov_breakdown: Dict[str, int] = {}
    for r in all_rows:
        st_breakdown[r.storage_type] = st_breakdown.get(r.storage_type, 0) + 1
        if r.provider:
            prov_breakdown[r.provider] = prov_breakdown.get(r.provider, 0) + 1

    return GGDatasourceStats(
        total_datasources=total,
        active_datasources=active,
        processed_datasources=processed,
        pending_datasources=pending,
        failed_datasources=failed_c,
        total_file_size=total_sz,
        storage_type_breakdown=st_breakdown,
        provider_breakdown=prov_breakdown,
    )


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
