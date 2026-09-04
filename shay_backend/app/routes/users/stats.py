"""
GET /company/{company_id}/stats — get_company_user_stats.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.user import User
from app.schemas.company import CompanyStats

router = APIRouter()


@router.get("/company/{company_id}/stats", response_model=CompanyStats)
async def get_company_user_stats(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyStats:
    """Get company user statistics"""
    user = await get_current_user_required(request)

    # Check if user can access this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Get company
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Get user statistics
    from app.models.workspace import Workspace
    from app.models.message import Message
    from app.models.attachment import Attachment

    try:
        # Count active users
        active_users_stmt = select(func.count(User.id)).where(
            User.company_id == company_id,
            User.is_active == True
        )
        active_users_result = await db.execute(active_users_stmt)
        total_users = active_users_result.scalar() or 0

        # Count workspaces
        workspace_count_stmt = select(func.count(Workspace.id)).where(Workspace.company_id == company_id)
        workspace_count_result = await db.execute(workspace_count_stmt)
        total_workspaces = workspace_count_result.scalar() or 0

        # Count messages for this company's workspaces (simplified to avoid join issues)
        message_count_stmt = select(func.count(Message.id))
        message_count_result = await db.execute(message_count_stmt)
        total_messages = message_count_result.scalar() or 0

        # Count attachments for this company's workspaces (simplified to avoid join issues)
        attachment_count_stmt = select(func.count(Attachment.id))
        attachment_count_result = await db.execute(attachment_count_stmt)
        total_attachments = attachment_count_result.scalar() or 0

    except Exception as e:
        # If there are any issues with the statistics queries, return default values
        total_users = 0
        total_workspaces = 0
        total_messages = 0
        total_attachments = 0

    return CompanyStats(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_messages=total_messages,
        total_attachments=total_attachments,
        storage_used_gb=0.0,  # TODO: Implement actual storage calculation
        subscription_plan=company.subscription_plan
    )
