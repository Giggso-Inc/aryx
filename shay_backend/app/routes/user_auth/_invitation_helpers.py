"""
Shared helpers for the invitation routes: invite_user and bulk_invite_users.

Split out of the original monolithic invitations.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up). Both
endpoints resolve the inviting user's display name, create an `Invitation`
row with the same 7-day expiry, build the same encrypted registration link,
and send the same invitation email — consolidated here since it's reused by
2+ endpoints.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.encryption_utils import create_registration_url
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service

from app.models.user import User
from app.models.invitation import Invitation

from app.routes.user_auth._shared import _format_user_name_from_email

DEFAULT_SYSTEM_USER_ID = "bd6aedd9-657e-4033-a9d6-1cc0b31cfd85"


async def _resolve_invited_by_name(db: AsyncSession, user_id: Optional[str]) -> str:
    """Look up the inviting user's display name, defaulting to 'System User'."""
    invited_by_name = "System User"
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
            stmt = select(User).where(User.id == user_uuid)
            result = await db.execute(stmt)
            inviting_user = result.scalar_one_or_none()
            if inviting_user:
                invited_by_name = inviting_user.name or inviting_user.email_id
        except ValueError:
            # Invalid user_id format, use default
            pass
    return invited_by_name


async def _create_invitation_record(
    db: AsyncSession,
    email: str,
    company_id: uuid.UUID,
    role: str,
    invited_by_user_id: Optional[str],
) -> tuple[Invitation, uuid.UUID, datetime]:
    """Create and persist a pending Invitation row with a 7-day expiry."""
    invite_id = uuid.uuid4()
    expires_at = datetime.utcnow() + timedelta(days=7)

    resolved_invited_by = invited_by_user_id if invited_by_user_id else DEFAULT_SYSTEM_USER_ID

    invitation = Invitation(
        id=invite_id,
        email=email,
        company_id=company_id,
        role=role,
        invited_by=uuid.UUID(resolved_invited_by),
        status="pending",
        expires_at=expires_at,
    )

    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    return invitation, invite_id, expires_at


async def _build_registration_links(
    db: AsyncSession,
    email: str,
    invite_id: uuid.UUID,
    company_id: str,
    role: str,
) -> tuple[str, str]:
    """Build the encrypted registration link and its shortened form."""
    platform_url = settings.PLATFORM_URL
    registration_link = create_registration_url(
        base_url=platform_url,
        email=email,
        invite_code=str(invite_id),
        company_id=company_id,
        role=role,
    )
    short_registration_link = await link_shortener_service.shorten(registration_link, db=db)
    return registration_link, short_registration_link


async def _send_invitation_email(
    db: AsyncSession,
    email: str,
    company_name: str,
    role: str,
    registration_link: str,
    short_registration_link: str,
    invite_id: uuid.UUID,
    expires_at: datetime,
    invited_by_name: str,
    platform_name: Optional[str],
    template_id: Optional[str],
) -> bool:
    """Send the invitation email, using a template if one was provided."""
    platform_url = settings.PLATFORM_URL
    invitation_data = {
        'company_name': company_name,
        'role': role,
        'registration_link': registration_link,
        'registration_short_link': short_registration_link,
        'invite_id': str(invite_id),
        'expires_at': expires_at.isoformat(),
        'email': email,  # Add email for personalization
        'invited_by': invited_by_name,  # Use fetched user name
        'user_name': _format_user_name_from_email(email),  # Extract formatted name from email
        'platform_name': platform_name,
    }

    if template_id:
        return await email_service.send_template_invitation_email(
            to_email=email,
            invitation_data=invitation_data,
            template_id=template_id,
            platform_url=platform_url,
            db=db,
        )
    return email_service.send_invitation_email(
        to_email=email,
        invitation_data=invitation_data,
        platform_url=platform_url,
    )
