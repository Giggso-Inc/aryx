"""
Pre-create lookup/validation helpers for company signup: domain-conflict
check, existing-user-by-email lookup, and encrypted-password decryption.
Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.
"""

from typing import Optional, Any
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.encryption_utils import decrypt
from app.models.user import User
from app.models.company import Company


async def _check_existing_company_conflict(db: AsyncSession, domain: Optional[str]) -> Optional[Company]:
    """
    Look up a company by domain (most recent first). Raises 409 if a company
    with this domain exists and is still active; returns it (inactive) so the
    caller can reactivate, or None if no company has this domain.
    """
    if not domain:
        return None
    existing_company_result = await db.execute(
        select(Company)
        .where(Company.domain == domain)
        .order_by(Company.created_at.desc())
        .limit(1)
    )
    existing_company = existing_company_result.scalar_one_or_none()

    if existing_company:
        if not existing_company.is_active:
            print(f"🔄 Found inactive company with domain '{domain}', will reactivate")
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Company with this domain already exists"
            )
    return existing_company


async def _get_existing_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Look up a user by email (used by create_company, no eager-loaded company)."""
    existing_user = await db.execute(
        select(User).where(User.email_id == email)
    )
    return existing_user.scalar_one_or_none()


async def _get_existing_user_with_company_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Look up a user by email, eager-loading its company (used by create_company_simple)."""
    existing_user = await db.execute(
        select(User).where(User.email_id == email).options(selectinload(User.company))
    )
    return existing_user.scalar_one_or_none()


async def _decrypt_password_if_needed(company_data: Any) -> str:
    """Decrypt the incoming password if the caller marked it as encrypted."""
    password_to_use = company_data.password
    if company_data.encrypted:
        try:
            password_to_use = decrypt(company_data.password)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )
    return password_to_use
