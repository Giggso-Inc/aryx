"""
Invitation routes: invite_user, decrypt_registration_invite, bulk_invite_users.

Split out of the original monolithic app/routes/user_auth.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5).
"""

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.config import settings
from app.core.encryption_utils import create_registration_url, decrypt_registration_params
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service

from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation

from app.schemas.user import (
    UserInviteRequest, UserInviteResponse,
    BulkUserInviteRequest, BulkUserInviteResponse,
    RegistrationInviteResponse,
)

from app.routes.user_auth._shared import _format_user_name_from_email

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
        except HTTPException as e:
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

    # Fetch invited_by user name if user_id is provided
    invited_by_name = "System User"  # Default fallback
    if invite_data.user_id:
        try:
            user_uuid = uuid.UUID(invite_data.user_id)
            stmt = select(User).where(User.id == user_uuid)
            result = await db.execute(stmt)
            inviting_user = result.scalar_one_or_none()
            if inviting_user:
                invited_by_name = inviting_user.name or inviting_user.email_id
        except ValueError:
            # Invalid user_id format, use default
            pass

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

    # Create invitation
    invite_id = uuid.uuid4()
    expires_at = datetime.utcnow() + timedelta(days=7)

    # Use provided user_id or default system user
    invited_by_user_id = invite_data.user_id if invite_data.user_id else "bd6aedd9-657e-4033-a9d6-1cc0b31cfd85"

    invitation = Invitation(
        id=invite_id,
        email=invite_data.email,
        company_id=company_uuid,
        role=invite_data.role,
        invited_by=uuid.UUID(invited_by_user_id),
        status="pending",
        expires_at=expires_at
    )

    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Generate encrypted registration link
    platform_url = settings.PLATFORM_URL
    registration_link = create_registration_url(
        base_url=platform_url,
        email=invite_data.email,
        invite_code=str(invite_id),
        company_id=str(invite_data.company_id),
        role=invite_data.role
    )
    short_registration_link = await link_shortener_service.shorten(registration_link, db=db)


    # Send invitation email
    invitation_data = {
        'company_name': company_name,
        'role': invite_data.role,
        'registration_link': registration_link,
        'registration_short_link': short_registration_link,
        'invite_id': str(invite_id),
        'expires_at': expires_at.isoformat(),
        'email': invite_data.email,  # Add email for personalization
        'invited_by': invited_by_name,  # Use fetched user name
        'user_name': _format_user_name_from_email(invite_data.email),  # Extract formatted name from email
        'platform_name': invite_data.platform_name
    }

    # Use template-based email if template_id is provided
    if invite_data.template_id:
        email_sent = await email_service.send_template_invitation_email(
            to_email=invite_data.email,
            invitation_data=invitation_data,
            template_id=invite_data.template_id,
            platform_url=platform_url,
            db=db
        )
    else:
        # Fallback to default email
        email_sent = email_service.send_invitation_email(
            to_email=invite_data.email,
            invitation_data=invitation_data,
            platform_url=platform_url
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


@router.get("/decrypt-registration", response_model=RegistrationInviteResponse)
async def decrypt_registration_invite(
    e: str
) -> RegistrationInviteResponse:
    """Decrypt an encrypted invitation payload for the registration page."""
    try:
        encrypted_invite_data = decrypt_registration_params(e)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted invitation format"
        )

    email_id = (encrypted_invite_data.get("email") or "").strip()
    invite_id = (encrypted_invite_data.get("invite_code") or "").strip()
    company_id = (encrypted_invite_data.get("company_id") or "").strip()
    role = (encrypted_invite_data.get("role") or "user").strip() or "user"

    if not email_id or not invite_id or not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted invitation format"
        )

    return RegistrationInviteResponse(
        email_id=email_id,
        invite_id=invite_id,
        company_id=company_id,
        role=role,
    )


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
        except HTTPException as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {bulk_invite_data.template_id}"
            )

    # Fetch invited_by user name if user_id is provided
    invited_by_name = "System User"  # Default fallback
    if bulk_invite_data.user_id:
        try:
            user_uuid = uuid.UUID(bulk_invite_data.user_id)
            stmt = select(User).where(User.id == user_uuid)
            result = await db.execute(stmt)
            inviting_user = result.scalar_one_or_none()
            if inviting_user:
                invited_by_name = inviting_user.name or inviting_user.email_id
        except ValueError:
            # Invalid user_id format, use default
            pass

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

            # Create invitation
            invite_id = uuid.uuid4()
            expires_at = datetime.utcnow() + timedelta(days=7)

            # Use provided user_id or default system user
            invited_by_user_id = bulk_invite_data.user_id if bulk_invite_data.user_id else "bd6aedd9-657e-4033-a9d6-1cc0b31cfd85"

            invitation = Invitation(
                id=invite_id,
                email=user_invite.email,
                company_id=user_invite.company_id,
                role=user_invite.role,
                invited_by=uuid.UUID(invited_by_user_id),
                status="pending",
                expires_at=expires_at
            )

            db.add(invitation)
            await db.commit()
            await db.refresh(invitation)

            # Generate encrypted registration link
            platform_url = settings.PLATFORM_URL
            registration_link = create_registration_url(
                base_url=platform_url,
                email=user_invite.email,
                invite_code=str(invite_id),
                company_id=str(user_invite.company_id),
                role=user_invite.role
            )
            short_registration_link = await link_shortener_service.shorten(registration_link, db=db)


            # Send invitation email
            invitation_data = {
                'company_name': company_name,
                'role': user_invite.role,
                'registration_link': registration_link,
                'registration_short_link': short_registration_link,
                'invite_id': str(invite_id),
                'expires_at': expires_at.isoformat(),
                'email': user_invite.email,  # Add email for personalization
                'invited_by': invited_by_name,  # Use fetched user name
                'user_name': _format_user_name_from_email(user_invite.email),  # Extract formatted name from email
                'platform_name': bulk_invite_data.platform_name
            }

            # Use template-based email if template_id is provided (only from bulk request)
            if bulk_invite_data.template_id:
                email_sent = await email_service.send_template_invitation_email(
                    to_email=user_invite.email,
                    invitation_data=invitation_data,
                    template_id=bulk_invite_data.template_id,
                    platform_url=platform_url,
                    db=db
                )
            else:
                # Fallback to default email
                email_sent = email_service.send_invitation_email(
                    to_email=user_invite.email,
                    invitation_data=invitation_data,
                    platform_url=platform_url
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
