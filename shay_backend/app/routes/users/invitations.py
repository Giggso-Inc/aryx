"""
DELETE /company/{company_id}/pendingInvitedUsers/{email_id} —
delete_pending_invited_user.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.invitation import Invitation

router = APIRouter()


@router.delete("/company/{company_id}/pendingInvitedUsers/{email_id}")
async def delete_pending_invited_user(
    company_id: str,
    email_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Delete pending invitations for a specific user by email and company.

    This endpoint allows admins to delete pending invitations from the gg_invitations table
    for a specific email address within a company. Only users with admin role can perform
    this operation.

    Args:
        company_id: UUID of the company
        email_id: Email address of the user whose pending invitations should be deleted
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        dict: Success message with count of deleted invitations

    Raises:
        HTTPException: 403 if user is not admin, 404 if no pending invitations found
    """
    # Get current user and verify authentication
    current_user = await get_current_user_required(request)

    # Check if user is admin - only admins can delete pending invitations
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete pending invitations"
        )

    # Check if user can access this company
    if not current_user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this company"
        )

    # Find all pending invitations for the specified email and company
    stmt = select(Invitation).where(
        and_(
            Invitation.email == email_id,
            Invitation.company_id == company_id,
            Invitation.status == "pending"
        )
    )
    result = await db.execute(stmt)
    pending_invitations = result.scalars().all()

    # Check if any pending invitations exist
    if not pending_invitations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending invitations found for email {email_id} in company {company_id}"
        )

    # Delete all pending invitations
    deleted_count = 0
    for invitation in pending_invitations:
        await db.delete(invitation)
        deleted_count += 1

    # Commit the transaction
    await db.commit()

    return {
        "message": f"Successfully deleted {deleted_count} pending invitation(s) for {email_id}",
        "deleted_count": deleted_count,
        "email": email_id,
        "company_id": company_id
    }
