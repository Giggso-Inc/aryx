"""
Datasource POST /from-upload/bulk endpoint (upload multiple files and
create a datasource row for each, in one call).
"""

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.datasource import DatasourceBulkResponse, DatasourceFromUploadBulk
from app.services.file_storage import get_file_storage_service

from ._from_upload_bulk_item import BulkItemFailure, process_from_upload_bulk_item

router = APIRouter()


@router.post("/from-upload/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_from_upload_bulk(
    datasources_data: DatasourceFromUploadBulk,
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> DatasourceBulkResponse:
    """Create multiple datasources from uploaded files"""
    user = await get_current_user_required(request)

    created_datasources = []
    failed_datasources = []

    # Validate that number of files matches number of datasources
    if len(files) != len(datasources_data.datasources):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of files must match number of datasources"
        )

    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Get file storage service
    storage_service = get_file_storage_service()

    for datasource_data, file in zip(datasources_data.datasources, files):
        try:
            created_datasources.append(
                await process_from_upload_bulk_item(
                    datasource_data, file, isValidationRequired, company, storage_service, user, db
                )
            )
        except BulkItemFailure as bulk_failure:
            failed_datasources.append({"name": bulk_failure.name, "error": bulk_failure.error})
        except Exception as e:
            failed_datasources.append({
                "name": datasource_data.name,
                "error": str(e)
            })

    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )
