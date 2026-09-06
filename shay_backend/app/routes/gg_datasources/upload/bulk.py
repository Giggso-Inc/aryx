"""POST /upload/bulk — upload multiple files to storage (no GGDatasource rows created)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.gg_datasource import FileUploadBulkResponse, FileUploadResponse
from ._helpers import _upload_single_file

router = APIRouter()


@router.post("/upload/bulk", response_model=FileUploadBulkResponse)
async def upload_files_bulk(
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> FileUploadBulkResponse:
    """Upload multiple files to storage (no GGDatasource rows created)."""
    user = await get_current_user_required(request, db)

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    uploaded_files: List[FileUploadResponse] = []
    failed_files: List[Dict[str, Any]] = []

    for file in files:
        try:
            upload_result = await _upload_single_file(file, company, isValidationRequired)
            uploaded_files.append(FileUploadResponse(
                filename=upload_result["original_filename"],
                storage_path=upload_result["storage_path"],
                file_url=upload_result["file_url"],
                file_size=upload_result["file_size"],
                file_type=upload_result["file_type"],
                provider=upload_result["provider"],
            ))
        except HTTPException as exc:
            failed_files.append({"filename": file.filename or "unknown", "error": exc.detail})
        except Exception as exc:
            failed_files.append({"filename": file.filename or "unknown", "error": str(exc)})

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files),
    )
