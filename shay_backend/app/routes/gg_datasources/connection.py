"""
Single-resource connect / disconnect / connection-status:

  POST   /{datasource_id}/connect
  POST   /{datasource_id}/disconnect
  GET    /{datasource_id}/connection-status
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import DatasourceConnectionResponse

router = APIRouter()


@router.post("/{datasource_id}/connect", response_model=DatasourceConnectionResponse)
async def connect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DatasourceConnectionResponse:
    """Connect a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    if ds.is_connected:
        raise HTTPException(status_code=400, detail="Datasource is already connected")

    ds.is_connected = True
    ds.updated_at   = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message="Datasource connected successfully",
        updated_at=ds.updated_at,
    )


@router.post("/{datasource_id}/disconnect", response_model=DatasourceConnectionResponse)
async def disconnect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DatasourceConnectionResponse:
    """Disconnect a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    if not ds.is_connected:
        raise HTTPException(status_code=400, detail="Datasource is already disconnected")

    ds.is_connected = False
    ds.updated_at   = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message="Datasource disconnected successfully",
        updated_at=ds.updated_at,
    )


@router.get("/{datasource_id}/connection-status", response_model=DatasourceConnectionResponse)
async def get_connection_status(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DatasourceConnectionResponse:
    """Get connection status of a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message=f"Datasource is {'connected' if ds.is_connected else 'disconnected'}",
        updated_at=ds.updated_at,
    )
