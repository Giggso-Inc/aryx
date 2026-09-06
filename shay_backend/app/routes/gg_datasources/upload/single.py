"""POST /upload — upload a single file to storage (no GGDatasource row created)."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.gg_datasource import FileUploadResponse
from ._helpers import _upload_single_file

router = APIRouter()


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
