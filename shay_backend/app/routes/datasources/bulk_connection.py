"""
Datasource POST /bulk-connection endpoint.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.schemas.datasource import (
    DatasourceBulkConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceConnectionResponse,
)

router = APIRouter()


@router.post("/bulk-connection", response_model=DatasourceBulkConnectionResponse)
async def bulk_manage_datasource_connections(
    connection_request: DatasourceConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceBulkConnectionResponse:
    """
    Bulk connect or disconnect multiple datasources

    This unified endpoint handles both connection and disconnection operations
    for multiple datasources in a single request, with optimized permission checking
    and batch processing.
    """
    user = await get_current_user_required(request)
    action = connection_request.action.lower()

    # Validate action
    if action not in ["connect", "disconnect"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Must be 'connect' or 'disconnect'"
        )

    # Get all datasources in a single query for efficiency
    stmt = select(Datasource).where(Datasource.id.in_(connection_request.datasource_ids))
    result = await db.execute(stmt)
    datasources = result.scalars().all()

    # Check if all datasources exist
    found_ids = {str(ds.id) for ds in datasources}
    missing_ids = set(connection_request.datasource_ids) - found_ids

    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Datasources not found: {', '.join(missing_ids)}"
        )

    successful_operations = []
    failed_operations = []

    # Process each datasource
    for datasource in datasources:
        try:
            # Check permissions through channel
            if not datasource.is_accessible_by_user(user.company_id, user.role):
                failed_operations.append({
                    "datasource_id": str(datasource.id),
                    "error": "Access denied to datasource",
                    "status_code": 403
                })
                continue

            # Check current connection status
            if action == "connect":
                if datasource.is_connected:
                    failed_operations.append({
                        "datasource_id": str(datasource.id),
                        "error": "Datasource is already connected",
                        "status_code": 400
                    })
                    continue
                # Connect the datasource
                datasource.is_connected = True
                message = "Datasource connected successfully"
            else:  # disconnect
                if not datasource.is_connected:
                    failed_operations.append({
                        "datasource_id": str(datasource.id),
                        "error": "Datasource is already disconnected",
                        "status_code": 400
                    })
                    continue
                # Disconnect the datasource
                datasource.is_connected = False
                message = "Datasource disconnected successfully"

            # Update timestamp
            datasource.updated_at = datetime.utcnow()

            # Add to successful operations
            successful_operations.append(DatasourceConnectionResponse(
                datasource_id=str(datasource.id),
                is_connected=datasource.is_connected,
                message=message,
                updated_at=datasource.updated_at
            ))

        except Exception as e:
            failed_operations.append({
                "datasource_id": str(datasource.id),
                "error": str(e),
                "status_code": 500
            })

    # Commit all changes if there are successful operations
    if successful_operations:
        await db.commit()

    # Build response
    total_successful = len(successful_operations)
    total_failed = len(failed_operations)

    response_message = f"Successfully {action}ed {total_successful} datasource(s)"
    if total_failed > 0:
        response_message += f", {total_failed} operation(s) failed"

    return DatasourceBulkConnectionResponse(
        successful_operations=successful_operations,
        failed_operations=failed_operations,
        total_successful=total_successful,
        total_failed=total_failed,
        action_performed=action,
        message=response_message
    )
