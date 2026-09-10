"""
Shared helper used by every task-attachment submodule: the Attachment model
-> TaskAttachmentResponse field-dict mapping (originally duplicated three
times verbatim across get_task_attachments / update_task_attachment /
bulk_upload_task_attachments in the pre-split attachments.py).
"""

from typing import Any, Dict

from app.models.attachment import Attachment


def _task_attachment_fields(attachment: Attachment) -> Dict[str, Any]:
    return {
        "id": attachment.id,
        "task_id": attachment.task_id,
        "filename": attachment.filename,
        "original_filename": attachment.original_filename,
        "file_size": attachment.file_size,
        "mime_type": attachment.mime_type,
        "file_extension": attachment.file_extension,
        "workspace_id": attachment.workspace_id,
        "user_id": attachment.user_id,
        "is_processed": attachment.is_processed,
        "processing_status": attachment.processing_status,
        "processing_error": attachment.processing_error,
        "is_public": attachment.is_public,
        "content_summary": attachment.content_summary,
        "log_entries_count": attachment.log_entries_count,
        "error_count": attachment.error_count,
        "warning_count": attachment.warning_count,
        "created_at": attachment.created_at,
        "updated_at": attachment.updated_at,
    }
