"""DELETE /{approval_id} — soft-delete a pending approval."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.services.audit_service import log as audit_log_write

router = APIRouter()


@router.delete("/{approval_id}")
async def delete_approval(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete an approval (soft delete by setting is_active to 'N')."""
    user = await get_current_user_required(request, db)

    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    # Check if user can delete this approval
    if str(approval.requested_by_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the requester can delete this approval"
        )

    # Only pending approvals can be deleted
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can be deleted"
        )

    await audit_log_write(db, user.id, "approval.deleted", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id)
    # Soft delete
    approval.is_active = "N"
    approval.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()

    return {"message": "Approval deleted successfully"}
