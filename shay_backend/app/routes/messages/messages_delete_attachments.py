"""
delete_message sub-step: delete the main message's attachments from
storage and unlink them.

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.message import Message
from app.services.file_storage import get_file_storage_service


async def delete_and_unlink_message_attachments(db: AsyncSession, message: Message) -> int:
    """Delete the message's attachment files from storage and unlink them.

    Returns the count of files successfully deleted from storage.
    """
    if not message.attachment_ids:
        return 0

    attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
    attachment_result = await db.execute(attachment_stmt)
    attachments = attachment_result.scalars().all()

    storage_service = get_file_storage_service()
    deleted_count = 0

    for attachment in attachments:
        try:
            print(f"Attempting to delete file from storage: {attachment.file_path}")
            print(f"Storage provider: {storage_service.provider.__class__.__name__}")
            result = await storage_service.delete_file(attachment.file_path)
            if result:
                deleted_count += 1
                print(f"Successfully deleted file: {attachment.file_path}")
            else:
                print(f"Failed to delete file (returned False): {attachment.file_path}")
        except Exception as e:
            print(f"Failed to delete file {attachment.file_path} from storage: {e}")
            import traceback
            traceback.print_exc()
            # Continue with unlinking even if storage deletion fails

        # Unlink attachment from message
        attachment.message_id = None

    return deleted_count
