"""
DELETE /company/{company_id}/users/{user_id} — remove_company_user.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2; further
split in wave B4 out of detail.py, one endpoint per file).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel_member import ChannelMember
from app.models.user import User

router = APIRouter()


@router.delete("/company/{company_id}/users/{user_id}")
async def remove_company_user(
    company_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Remove a user from a company (admin only)"""
    current_user = await get_current_user_required(request)

    # Check if user can manage this company
    if current_user.company_id != company_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can remove users"
        )

    # Prevent self-removal
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the company"
        )

    stmt = select(User).where(
        User.id == user_id,
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Revoke channel memberships before removing user
    channel_memberships_stmt = select(ChannelMember).where(ChannelMember.user_id == user_id)
    channel_memberships_result = await db.execute(channel_memberships_stmt)
    channel_memberships = channel_memberships_result.scalars().all()

    # Deactivate all channel memberships
    for membership in channel_memberships:
        membership.is_active = False
        membership.updated_at = func.current_timestamp()

    # Deactivate user instead of deleting
    target_user.is_active = False
    target_user.company_id = None

    await db.commit()

    return {
        "message": "User removed from company successfully",
        "revoked_channel_memberships": len(channel_memberships)
    }
