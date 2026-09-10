"""PUT /{datasource_id}/status — ML callback to report processing / embedding progress."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse, ProcessingStatusUpdate
from ..response import _to_response

router = APIRouter()


@router.put("/{datasource_id}/status", response_model=GGDatasourceResponse)
async def update_processing_status(
    datasource_id: str,
    payload: ProcessingStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    """Called by ML agents to report processing / embedding progress."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ds, field, value)

    if payload.processing_status == "completed":
        ds.last_processed_at = datetime.utcnow()

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)
