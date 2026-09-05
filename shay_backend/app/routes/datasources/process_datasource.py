"""
Datasource POST /process endpoint and its background task.
"""

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceProcessingRequest, DatasourceProcessingResponse

router = APIRouter()


@router.post("/process", response_model=DatasourceProcessingResponse)
async def process_datasources(
    processing_request: DatasourceProcessingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceProcessingResponse:
    """Process datasources in background"""
    user = await get_current_user_required(request)

    # Get datasource
    stmt = select(Datasource).where(Datasource.id == processing_request.datasource_id)
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

    # Add background task
    background_tasks.add_task(
        process_datasource_background,
        processing_request.datasource_id
    )

    return DatasourceProcessingResponse(
        datasource_id=processing_request.datasource_id,
        status="processing_started",
        message="Datasource processing started in background"
    )


async def process_datasource_background(datasource_id: str) -> None:
    """Background task to process datasource"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get datasource
            stmt = select(Datasource).where(Datasource.id == datasource_id)
            result = await db.execute(stmt)
            datasource = result.scalar_one_or_none()

            if not datasource:
                return

            # Mark as processing
            datasource.mark_processing_started()
            await db.commit()

            # Close session before long operation
            await db.close()

            # Simulate processing (replace with actual processing logic)
            await asyncio.sleep(5)

            # Create new session for final operations
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()

                if datasource:
                    # Mark as completed
                    datasource.mark_processing_completed(record_count=100, processing_time=5000)
                    await db.commit()

        except Exception as e:
            # Create new session for error handling
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()

                if datasource:
                    datasource.mark_processing_failed(str(e))
                    await db.commit()
