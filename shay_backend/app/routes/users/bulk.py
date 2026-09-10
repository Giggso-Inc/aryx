"""
DELETE /company/{company_id}/users — bulk_remove_company_users.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel_member import ChannelMember
from app.models.user import User
from app.schemas.user import BulkRemoveUsersRequest, BulkRemoveUsersResponse

router = APIRouter()


@router.delete("/company/{company_id}/users", response_model=BulkRemoveUsersResponse)
async def bulk_remove_company_users(
    company_id: UUID,
    body: BulkRemoveUsersRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> BulkRemoveUsersResponse:
    current_user = await get_current_user_required(request)

    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can remove users")
    if str(current_user.company_id) != str(company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if UUID(str(current_user.id)) in body.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove yourself from the company")

    stmt = select(User).where(
        User.id.in_(body.user_ids),
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    found_users = result.scalars().all()

    if not found_users:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="None of the requested users were found in the company")

    found_ids = {UUID(str(u.id)) for u in found_users}
    not_found_user_ids = [str(user_id) for user_id in body.user_ids if user_id not in found_ids]
    current_time = datetime.now(timezone.utc)

    # Revoke channel memberships before removing users
    channel_memberships_stmt = select(ChannelMember).where(ChannelMember.user_id.in_(found_ids))
    channel_memberships_result = await db.execute(channel_memberships_stmt)
    channel_memberships = channel_memberships_result.scalars().all()

    # Deactivate all channel memberships
    for membership in channel_memberships:
        membership.is_active = False
        membership.updated_at = current_time

    # Deactivate users instead of deleting
    for user in found_users:
        user.is_active = False
        user.company_id = None
        user.updated_datetime = current_time

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove users")

    return {
        "message": f"{len(found_users)} user(s) removed from company successfully",
        "removed_user_ids": [str(user.id) for user in found_users],
        "not_found_user_ids": not_found_user_ids,
        "revoked_channel_memberships": len(channel_memberships)
    }
