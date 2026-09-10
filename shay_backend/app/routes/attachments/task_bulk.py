"""
Task-attachment bulk upload:

  POST   /task/{task_id}/bulk-upload

Stated exception (bug preserved as-is, same root cause as task_upload.py):
`file_path=storage_info.get("file_path", destination_path)` references
`destination_path`, which this function never assigns (only
`structured_path` is defined) — every per-file iteration raises NameError,
which the handler's own bottom `except Exception` catches and reports as a
500. Characterized by
tests/test_attachments_characterization.py::TestBulkUploadTaskAttachments,
not fixed here.

Stated exception (structure): the upload/commit/refresh/cleanup-on-failure
block below is left as one atomic try/except rather than split further —
`attachments` is shared mutable state across the loop, the commit, the
refresh pass, and the cleanup-on-failure branch, so splitting it would
require threading that state back out through extra parameters/returns
without removing any real complexity.
"""

from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.attachment import TaskAttachmentResponse
from app.services.file_storage import get_file_storage_service
from .helpers import _task_attachment_fields
from .task_access import _check_task_access, _get_company_or_404, _get_task_or_404
from .task_bulk_helpers import _process_one_file, _validate_file_count, _validate_total_size

router = APIRouter()


@router.post("/task/{task_id}/bulk-upload", response_model=List[TaskAttachmentResponse])
async def bulk_upload_task_attachments(
    task_id: str,
    files: List[UploadFile] = File(...),
    is_public: bool = Query(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> List[TaskAttachmentResponse]:
    """Upload multiple file attachments to a specific task"""
    user = await get_current_user_required(request)

    _validate_file_count(files)

    task = await _get_task_or_404(db, task_id)
    await _check_task_access(db, task, user)
    company = await _get_company_or_404(db, user.company_id)

    _validate_total_size(files)

    attachments = []
    storage_service = get_file_storage_service()

    try:
        for file in files:
            attachment = await _process_one_file(
                file, task_id, task, company, user, is_public, storage_service
            )
            attachments.append(attachment)

        # Add all attachments to database
        db.add_all(attachments)
        await db.commit()

        # Refresh all attachments
        for attachment in attachments:
            await db.refresh(attachment)

        # Convert to response models
        task_attachments = [
            TaskAttachmentResponse(**_task_attachment_fields(attachment))
            for attachment in attachments
        ]

        return task_attachments

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # If any other error occurs, try to clean up uploaded files
        for attachment in attachments:
            try:
                if hasattr(attachment, 'file_path') and attachment.file_path:
                    await storage_service.delete_file(attachment.file_path)
            except:
                pass  # Ignore cleanup errors

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk task upload failed: {str(e)}"
        )
