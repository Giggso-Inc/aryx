"""
Datasource GET /{datasource_id}/connection-status endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceConnectionResponse

router = APIRouter()


@router.get("/{datasource_id}/connection-status", response_model=DatasourceConnectionResponse)
async def get_datasource_connection_status(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceConnectionResponse:
    """Get the connection status of a datasource"""
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

    status_message = "connected" if datasource.is_connected else "disconnected"

    return DatasourceConnectionResponse(
        datasource_id=str(datasource.id),
        is_connected=datasource.is_connected,
        message=f"Datasource is {status_message}",
        updated_at=datasource.updated_at
    )
