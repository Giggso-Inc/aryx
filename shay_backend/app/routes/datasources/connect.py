"""
Datasource POST /{datasource_id}/connect endpoint (legacy single operation).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceConnectionResponse

router = APIRouter()


@router.post("/{datasource_id}/connect", response_model=DatasourceConnectionResponse)
async def connect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceConnectionResponse:
    """Connect a datasource to the topic level (Legacy single operation endpoint)"""
    user = await get_current_user_required(request)

    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )

    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )

    # Check if datasource is already connected
    if datasource.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datasource is already connected"
        )

    # Connect the datasource
    datasource.is_connected = True
    datasource.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(datasource)

    return DatasourceConnectionResponse(
        datasource_id=str(datasource.id),
        is_connected=datasource.is_connected,
        message="Datasource connected successfully",
        updated_at=datasource.updated_at
    )
