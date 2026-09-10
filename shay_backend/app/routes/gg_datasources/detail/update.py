"""PUT /{datasource_id} and DELETE /{datasource_id} — update / soft-delete."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse, GGDatasourceUpdate
from ..response import _to_response

router = APIRouter()


@router.put("/{datasource_id}", response_model=GGDatasourceResponse)
async def update_datasource(
    datasource_id: str,
    payload: GGDatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        if field == "vault_unique_id" and value:
            value = UUID(value)
        setattr(ds, field, value)

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    ds.is_active  = False
    ds.updated_at = datetime.utcnow()
    await db.commit()
