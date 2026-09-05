"""
Invitation route: bulk_invite_users.

Split out of the original monolithic invitations.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up). Steps
shared with invite.py live in `_invitation_helpers.py`.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db

from app.models.company import Company
from app.models.user import User

from app.schemas.user import BulkUserInviteRequest, BulkUserInviteResponse, UserInviteResponse

from app.routes.user_auth._invitation_helpers import (
    _resolve_invited_by_name, _create_invitation_record,
    _build_registration_links, _send_invitation_email,
)

router = APIRouter()


@router.post("/bulk-invite", response_model=BulkUserInviteResponse)
async def bulk_invite_users(
    bulk_invite_data: BulkUserInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> BulkUserInviteResponse:
    """Send bulk user invitations"""
    # Validate template exists if template_id is provided
    if bulk_invite_data.template_id:
        try:
            from app.services.template_service import template_service
            await template_service.get_template_content(bulk_invite_data.template_id, db)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {bulk_invite_data.template_id}"
            )

    invited_by_name = await _resolve_invited_by_name(db, bulk_invite_data.user_id)

    successful_invitations = []
    failed_invitations = []

    for user_invite in bulk_invite_data.users:
        try:
            # Validate company exists
            stmt = select(Company).where(Company.id == user_invite.company_id)
            result = await db.execute(stmt)
            company = result.scalar_one_or_none()

            if not company:
                failed_invitations.append({
                    "email_id": user_invite.email,
                    "reason": "Company not found"
                })
                continue
            company_name = company.name

            # Check if user already exists
            stmt = select(User).where(User.email_id == user_invite.email)
            result = await db.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user and existing_user.is_active:
                failed_invitations.append({
                    "email_id": user_invite.email,
                    "reason": "User with this email already exists"
                })
                continue

            _invitation, invite_id, expires_at = await _create_invitation_record(
                db, user_invite.email, user_invite.company_id, user_invite.role,
                bulk_invite_data.user_id,
            )

            registration_link, short_registration_link = await _build_registration_links(
                db, user_invite.email, invite_id, str(user_invite.company_id), user_invite.role
            )

            # Use template-based email if template_id is provided (only from bulk request)
            email_sent = await _send_invitation_email(
                db, user_invite.email, company_name, user_invite.role,
                registration_link, short_registration_link, invite_id, expires_at,
                invited_by_name, bulk_invite_data.platform_name, bulk_invite_data.template_id,
            )

            message = "Invitation sent successfully" + (" (Email sent)" if email_sent else " (Email failed)")

            successful_invitations.append(UserInviteResponse(
                message=message,
                invite_id=str(invite_id),
                email_id=user_invite.email,
                registration_link=short_registration_link,
                expires_at=expires_at
            ))

        except Exception as e:
            failed_invitations.append({
                "email_id": user_invite.email,
                "reason": f"Error: {str(e)}"
            })

    await db.commit()

    return BulkUserInviteResponse(
        message=f"Bulk invitation completed. {len(successful_invitations)} successful, {len(failed_invitations)} failed",
        total_invited=len(successful_invitations),
        successful_invitations=successful_invitations,
        failed_invitations=failed_invitations
    )
