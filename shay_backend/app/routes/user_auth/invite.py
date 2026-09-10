"""
Invitation route: invite_user.

Split out of the original monolithic invitations.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up). Steps
shared with bulk_invite.py live in `_invitation_helpers.py`.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db

from app.models.company import Company
from app.models.user import User
from app.models.invitation import Invitation

from app.schemas.user import UserInviteRequest, UserInviteResponse

from app.routes.user_auth._invitation_helpers import (
    _resolve_invited_by_name, _create_invitation_record,
    _build_registration_links, _send_invitation_email,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/invite", response_model=UserInviteResponse)
async def invite_user(
    invite_data: UserInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> UserInviteResponse:
    """Send user invitation to email with platform link"""
    # Validate template exists if template_id is provided
    if invite_data.template_id:
        try:
            from app.services.template_service import template_service
            await template_service.get_template_content(invite_data.template_id, db)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {invite_data.template_id}"
            )

    # Validate company exists
    try:
        company_uuid = uuid.UUID(invite_data.company_id)
        stmt = select(Company).where(Company.id == company_uuid)
        result = await db.execute(stmt)
        company = result.scalar_one_or_none()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid company_id format: {str(e)}"
        )

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    company_name = company.name

    invited_by_name = await _resolve_invited_by_name(db, invite_data.user_id)

    # Check if user already exists
    stmt = select(User).where(User.email_id == invite_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if existing_user and existing_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )

    # Check if invitation already exists
    existing_invitation_stmt = select(Invitation).where(
        and_(
            Invitation.email == invite_data.email,
            Invitation.company_id == company_uuid,
            Invitation.status == "pending"
        )
    )
    existing_invitation_result = await db.execute(existing_invitation_stmt)
    existing_invitation = existing_invitation_result.scalar_one_or_none()

    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation already exists for this email"
        )

    _invitation, invite_id, expires_at = await _create_invitation_record(
        db, invite_data.email, company_uuid, invite_data.role, invite_data.user_id
    )

    registration_link, short_registration_link = await _build_registration_links(
        db, invite_data.email, invite_id, str(invite_data.company_id), invite_data.role
    )

    email_sent = await _send_invitation_email(
        db, invite_data.email, company_name, invite_data.role,
        registration_link, short_registration_link, invite_id, expires_at,
        invited_by_name, invite_data.platform_name, invite_data.template_id,
    )

    if not email_sent:
        logger.warning("Invitation created but email delivery failed — to=%s", invite_data.email)

    return UserInviteResponse(
        message="Invitation sent successfully" + (" (Email sent)" if email_sent else " (Email failed)"),
        invite_id=str(invite_id),
        email_id=invite_data.email,
        registration_link=short_registration_link,
        expires_at=expires_at
    )
