"""Resolve (or create) the local User for an SSO identity, and its default workspace."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_user_id, generate_workspace_id
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace
from .errors import (
    EmailMismatchError,
    InvitationInvalidError,
    InvitationNotFoundError,
    ProviderError,
    SignupInviteRequiredError,
)


async def resolve_sso_user(
    db: AsyncSession,
    provider_id_field: str,
    provider_id_value: str,
    email: str,
    name: str,
    avatar_url: Optional[str],
    invite_id: str,
    provider_name: str,
) -> User:
    # Resolve by provider id first (returning SSO user — no invitation).
    provider_result = await db.execute(
        select(User).where(getattr(User, provider_id_field) == provider_id_value)
    )
    provider_user = provider_result.scalar_one_or_none()

    # Resolve by email for link / returning-by-email / guard.
    email_result = await db.execute(select(User).where(User.email_id == email))
    email_user = email_result.scalar_one_or_none()

    # Guard: same provider identity must not map to a different local user than this email.
    if provider_user and email_user and str(provider_user.id) != str(email_user.id):
        raise ProviderError(provider_name.title())

    # Returning user: matched by provider id.
    if provider_user:
        provider_user.last_login = datetime.utcnow()
        await db.commit()
        await db.refresh(provider_user)
        return provider_user

    # Returning user: matched by email with this provider already linked.
    linked_id = getattr(email_user, provider_id_field, None) if email_user else None
    if email_user and linked_id:
        if linked_id != provider_id_value:
            raise ProviderError(provider_name.title())
        email_user.last_login = datetime.utcnow()
        await db.commit()
        await db.refresh(email_user)
        return email_user

    # Existing local user, same email, not yet linked to this provider — link and skip invitation.
    if email_user:
        setattr(email_user, provider_id_field, provider_id_value)
        email_user.oauth_provider = provider_name
        if not email_user.avatar_url and avatar_url:
            email_user.avatar_url = avatar_url
        if not email_user.is_verified:
            email_user.is_verified = True
        await db.commit()
        await db.refresh(email_user)
        return email_user

    # Brand-new user: invitation is required (invite_id omitted => cannot create account).
    invite_id_clean = (invite_id or "").strip()
    if not invite_id_clean:
        raise SignupInviteRequiredError()
    try:
        invite_uuid = uuid.UUID(invite_id_clean)
    except ValueError:
        raise InvitationNotFoundError()
    result = await db.execute(select(Invitation).where(Invitation.id == invite_uuid))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise InvitationNotFoundError()
    if not invitation.is_valid:
        raise InvitationInvalidError()
    if invitation.email.lower() != email.lower():
        raise EmailMismatchError(provider_name)

    new_user = User(
        id=generate_user_id(),
        email_id=email,
        name=name or email.split("@")[0],
        avatar_url=avatar_url,
        company_id=invitation.company_id,
        role=invitation.role,
        is_active=True,
        is_verified=True,
        oauth_provider=provider_name,
        password_hash=None,
        **{provider_id_field: provider_id_value},
    )
    db.add(new_user)
    await db.flush()  # keep same transaction for workspace creation.
    await _create_default_workspace_if_not_exists(db, new_user)
    invitation.mark_as_used()
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def _create_default_workspace_if_not_exists(db: AsyncSession, user: User) -> None:
    company_result = await db.execute(select(Company).where(Company.id == user.company_id))
    company = company_result.scalar_one_or_none()
    if not company:
        return
    stmt = select(Workspace).where(
        and_(
            Workspace.company_id == user.company_id,
            Workspace.name == company.name,
            Workspace.is_active == True,
        )
    )
    result = await db.execute(stmt)
    default_workspace = result.scalar_one_or_none()
    if not default_workspace:
        default_workspace = Workspace(
            id=generate_workspace_id(),
            name=company.name,
            description=f"Default workspace for {company.name}",
            company_id=user.company_id,
            created_by=user.id,
            is_active=True,
            is_public=False,
            ai_enabled=True,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(default_workspace)
        await db.flush()  # keep creation inside the current transaction.
