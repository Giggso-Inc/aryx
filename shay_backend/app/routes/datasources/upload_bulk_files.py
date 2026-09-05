"""
Datasource POST /upload/bulk endpoint (upload multiple files to storage,
optionally kicking off Aryx knowledge-graph ingestion per file).

Stated exception (177 lines): ~45 lines are docstring/comments describing
the additive Aryx behavior (kept verbatim — it documents a real backward-
compatibility guarantee); the per-file loop body itself is one cohesive
upload-then-optionally-ingest sequence that doesn't split into independent
reusable pieces the way the other bulk endpoints' loops did.
"""

import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.routes.aryx import (
    _resolve_aryx_workspace_id as _resolve_aryx_workspace_id_for_datasources,
    call_aryx_docs_read,
)
from app.routes.workspaces import _get_workspace_or_404
from app.schemas.datasource import FileUploadBulkResponse
from app.services.file_storage import generate_structured_path, get_file_storage_service
from app.utils.file_validation import validate_file_content
from app.utils.permissions import require_active_workspace_role
from sqlalchemy import select

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
    aryx_workspace_id: Optional[int] = None
    aryx_setup_error: Optional[str] = None
    if kind == "aryx":
        if not workspace_id:
            aryx_setup_error = "workspace_id is required when kind='aryx'"
        else:
            try:
                target_workspace = await _get_workspace_or_404(db, workspace_id)
                await require_active_workspace_role(db, user.id, uuid.UUID(str(target_workspace.id)))
                aryx_workspace_id = await _resolve_aryx_workspace_id_for_datasources(workspace_id)
            except HTTPException as exc:
                aryx_setup_error = str(exc.detail)

    # Get file storage service
    storage_service = get_file_storage_service()

    uploaded_files = []
    failed_files = []

    for file in files:
        try:
            # Validate file
            if not file.filename:
                failed_files.append({
                    "filename": "unknown",
                    "error": "File name is required"
                })
                continue

            # Read file content
            file_content = await file.read()

            # Validate file content before uploading (if validation is required)
            if isValidationRequired and not validate_file_content(file_content, file.filename):
                failed_files.append({
                    "filename": file.filename,
                    "error": "File validation failed - no valid section headers found"
                })
                continue

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

            uploaded_entry = {
                "filename": file.filename,
                "storage_path": upload_result["storage_path"],
                "file_url": upload_result["file_url"],
                "file_size": len(file_content),
                "file_type": file.content_type or "application/octet-stream",
                "provider": upload_result["provider"]
            }

            # --- Additive: start Aryx ingestion for this file using the
            # bytes already read above. Never touches uploaded_entry's
            # existing keys — only adds aryx_ingestion.
            if kind == "aryx":
                if aryx_setup_error:
                    uploaded_entry["aryx_ingestion"] = {"error": aryx_setup_error}
                else:
                    try:
                        aryx_result = await call_aryx_docs_read(
                            aryx_workspace_id,
                            [(file.filename, file_content, file.content_type)],
                        )
                        uploaded_entry["aryx_ingestion"] = {
                            "discovery_id": aryx_result.get("discovery_id"),
                            "status": "queued",
                        }
                    except HTTPException as exc:
                        uploaded_entry["aryx_ingestion"] = {"error": str(exc.detail)}

            uploaded_files.append(uploaded_entry)

        except Exception as e:
            failed_files.append({
                "filename": file.filename,
                "error": str(e)
            })

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files)
    )
