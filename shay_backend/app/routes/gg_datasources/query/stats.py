"""GET /stats — datasource statistics (scope-filtered)."""

from typing import Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceStats

router = APIRouter()


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
