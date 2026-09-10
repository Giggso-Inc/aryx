"""
Datasource POST /upload/bulk endpoint (upload multiple files to storage,
optionally kicking off Aryx knowledge-graph ingestion per file).

The per-batch Aryx setup and the per-file upload-then-optionally-ingest
step are split out to _upload_bulk_files_aryx_setup.py and
_upload_bulk_files_item.py (Raven style-compliance, wave B4) — what
remains here is the endpoint itself: resolve the company, resolve the
batch-level Aryx setup once, then loop.
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.datasource import FileUploadBulkResponse
from app.services.file_storage import get_file_storage_service

from ._upload_bulk_files_aryx_setup import _resolve_aryx_setup_for_bulk_upload
from ._upload_bulk_files_item import _upload_one_bulk_file

router = APIRouter()


@router.post("/upload/bulk", response_model=FileUploadBulkResponse)
async def upload_files_bulk(
    files: list[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    kind: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> FileUploadBulkResponse:
    """Upload multiple files to the system.

    Additive Aryx integration: pass kind="aryx" together with workspace_id
    (a Shay workspace UUID already bridged to Aryx) to ALSO start Aryx
    knowledge-graph ingestion for each successfully-uploaded file, using the
    same bytes already read for the storage upload — no re-read, no
    duplicate network transfer of the file. This runs ALONGSIDE the existing
    storage upload below, never instead of it: the storage-upload result is
    always computed and appended first, exactly as before; the Aryx result
    (or a per-file error) is then attached as an additional aryx_ingestion
    key on that same entry.

    Omitting kind (or any value other than "aryx") is byte-for-byte
    identical to the endpoint's behavior before this change — no existing
    caller is affected.
    """
    user = await get_current_user_required(request)

    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # --- Additive Aryx setup — resolved once for the whole batch, only when
    # kind="aryx" was actually requested. Any failure here becomes a per-file
    # aryx_ingestion.error below rather than a hard failure of the upload
    # (which must still succeed for callers not opting into this feature).
    aryx_workspace_id, aryx_setup_error = await _resolve_aryx_setup_for_bulk_upload(
        db, user, kind, workspace_id
    )

    # Get file storage service
    storage_service = get_file_storage_service()

    uploaded_files = []
    failed_files = []

    for file in files:
        uploaded_entry, failed_entry = await _upload_one_bulk_file(
            file, company, isValidationRequired, kind,
            aryx_workspace_id, aryx_setup_error, storage_service,
        )
        if uploaded_entry is not None:
            uploaded_files.append(uploaded_entry)
        if failed_entry is not None:
            failed_files.append(failed_entry)

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files)
    )
