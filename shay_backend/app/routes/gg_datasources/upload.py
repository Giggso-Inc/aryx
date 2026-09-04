"""
Plain file-upload endpoints (no GGDatasource row created) plus the two
supporting lookups:

  GET    /supported-log-types
  GET    /environment
  POST   /upload
  POST   /upload/bulk

`_upload_single_file` / `_build_config_from_upload` are also imported by
`app.routes.gg_datasources.create_from_upload`, which builds a GGDatasource
row on top of an upload.
"""

import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.gg_datasource import FileUploadBulkResponse, FileUploadResponse
from app.services.file_storage import get_file_storage_service, generate_structured_path
from app.utils.file_validation import validate_file_content

router = APIRouter()


async def _upload_single_file(
    file: UploadFile,
    company: Company,
    is_validation_required: bool,
) -> Dict[str, Any]:
    """Upload a file to storage and return upload_result dict. Raises HTTPException on failure."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    storage_service = get_file_storage_service()
    file_content = await file.read()

    if is_validation_required and not validate_file_content(file_content, file.filename):
        raise HTTPException(
            status_code=400,
            detail="File validation failed - no valid section headers found",
        )

    file_extension = os.path.splitext(file.filename)[1]
    base_filename  = os.path.splitext(file.filename)[0]
    current_date   = datetime.now().strftime("%Y-%m-%d")

    structured_path = generate_structured_path(
        company_name=company.name,
        company_id=str(company.id),
        file_type="datasource",
        original_filename=file.filename,
        base_filename=base_filename,
        file_extension=file_extension,
        current_date=current_date,
    )

    upload_result = await storage_service.upload_file(
        file_content=file_content,
        destination_path=structured_path,
        original_filename=file.filename,
    )
    upload_result["file_content"] = file_content
    upload_result["file_size"]    = len(file_content)
    upload_result["file_type"]    = file.content_type or "application/octet-stream"
    upload_result["original_filename"] = file.filename
    return upload_result


def _build_config_from_upload(upload_result: Dict[str, Any]) -> Dict[str, Any]:
    provider = upload_result.get("provider", "")
    config: Dict[str, Any] = {
        "file_path":         upload_result.get("storage_path"),
        "original_filename": upload_result.get("original_filename"),
    }
    if provider == "aws":
        config.update({"bucket_name": upload_result.get("bucket_name"), "region": upload_result.get("region")})
    elif provider == "azure":
        config.update({"container_name": upload_result.get("container_name"), "account_name": upload_result.get("account_name")})
    elif provider == "oracle":
        config.update({"bucket_name": upload_result.get("bucket_name"), "namespace": upload_result.get("namespace"), "compartment_id": upload_result.get("compartment_id")})
    return config


@router.get("/supported-log-types", response_model=List[str])
async def get_supported_log_types() -> List[str]:
    """Get list of supported log types configured in environment."""
    return settings.SUPPORTED_LOG_TYPES


@router.get("/environment", response_model=Dict[str, Any])
async def get_environment_config() -> Dict[str, Any]:
    """Get current environment configuration for debugging vault settings."""
    from app.services.vault_data_builder import get_environment_info
    return get_environment_info()


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> FileUploadResponse:
    """Upload a single file to storage (no GGDatasource row created)."""
    user = await get_current_user_required(request, db)

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        upload_result = await _upload_single_file(file, company, isValidationRequired)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {exc}")

    return FileUploadResponse(
        filename=upload_result["original_filename"],
        storage_path=upload_result["storage_path"],
        file_url=upload_result["file_url"],
        file_size=upload_result["file_size"],
        file_type=upload_result["file_type"],
        provider=upload_result["provider"],
    )


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
