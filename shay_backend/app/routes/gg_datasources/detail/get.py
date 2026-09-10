"""GET /{datasource_id} — fetch a single GGDatasource by ID."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse
from ..response import _to_response

router = APIRouter()


@router.get("/{datasource_id}", response_model=GGDatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    return _to_response(ds)
