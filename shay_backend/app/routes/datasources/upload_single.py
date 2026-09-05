"""
Datasource POST /upload endpoint (upload a single file to storage, no datasource row).
"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.datasource import FileUploadResponse
from app.services.file_storage import generate_structured_path, get_file_storage_service
from app.utils.file_validation import validate_file_content
from sqlalchemy import select

router = APIRouter()


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> FileUploadResponse:
    """Upload a single file to the system"""
    user = await get_current_user_required(request)

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required"
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

    try:
        # Read file content
        file_content = await file.read()

        # Validate file content before uploading (if validation is required)
        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )

        # Generate structured path
        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Use structured path for datasource files
        structured_path = generate_structured_path(
            company_name=company.name,
            company_id=str(company.id),
            file_type="datasource",
            original_filename=file.filename,
            base_filename=base_filename,
            file_extension=file_extension,
            current_date=current_date
        )

        # Upload file with structured path
        upload_result = await storage_service.upload_file(
            file_content=file_content,
            destination_path=structured_path,
            original_filename=file.filename
        )

        return FileUploadResponse(
            filename=file.filename,
            storage_path=upload_result["storage_path"],
            file_url=upload_result["file_url"],
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            provider=upload_result["provider"]
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )
