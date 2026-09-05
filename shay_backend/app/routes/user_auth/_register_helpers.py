"""
Private helpers for register.py's register_user endpoint.

Split out of registration.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up) so
register.py itself stays under the 150-line limit. These are only used by
register_user; none of these names are patched by tests.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.encryption_utils import decrypt_registration_params
from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation


def _apply_invite_param_overrides(register_data) -> None:
    """Decrypt an encrypted_param invite payload and overlay it onto register_data in place."""
    if not register_data.encrypted_param:
        return

    try:
        encrypted_invite_data = decrypt_registration_params(register_data.encrypted_param)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted invitation format"
        )

    invited_email = (encrypted_invite_data.get("email") or "").strip()
    if invited_email and not register_data.email_id:
        register_data.email_id = invited_email
    if invited_email and invited_email != register_data.email_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email does not match invitation"
        )

    register_data.invite_id = encrypted_invite_data.get("invite_code") or register_data.invite_id
    register_data.company_id = encrypted_invite_data.get("company_id") or register_data.company_id
    register_data.role = encrypted_invite_data.get("role") or register_data.role


async def _resolve_registration_target(db, register_data) -> tuple:
    """
    Resolve (company_id, role) for a registration, validating the invite or company.

    Returns the invitation record too (or None) so the caller can mark it used.
    """
    if register_data.invite_id:
        try:
            invite_uuid = uuid.UUID(register_data.invite_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation ID format. Must be a valid UUID."
            )

        stmt = select(Invitation).where(Invitation.id == invite_uuid)
        result = await db.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found"
            )
        if invitation.status == "used":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has already been used"
            )
        if invitation.status == "expired" or not invitation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has expired"
            )
        if invitation.email != register_data.email_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation"
            )

        invitation.status = "used"
        invitation.updated_at = datetime.utcnow()
        return invitation.company_id, invitation.role, invitation

    if not register_data.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company ID is required when registering without invitation"
        )

    stmt = select(Company).where(Company.id == register_data.company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    return register_data.company_id, register_data.role or "user", None


def _derive_user_name(register_data) -> str:
    """Determine the display name: explicit name, else derived from email, else default."""
    if register_data.name and register_data.name.strip():
        return register_data.name.strip()
    if register_data.email_id:
        return register_data.email_id.split('@')[0].replace('.', ' ').title()
    return "User"


def _upsert_registered_user(db, register_data, company_id, role, password_hash, existing_user, user_name):
    """Update an existing (previously removed) user record or create a new one."""
    if existing_user:
        user = existing_user
        user.name = user_name
        user.email_id = register_data.email_id
        user.company_id = company_id
        user.role = role
        user.is_active = True
        user.is_verified = True
        user.password_hash = password_hash
        user.updated_datetime = datetime.utcnow()
        return user

    user = User(
        id=uuid.uuid4(),
        name=user_name,
        email_id=register_data.email_id,
        company_id=company_id,
        role=role,
        is_verified=True,
        password_hash=password_hash
    )
    db.add(user)
    return user
