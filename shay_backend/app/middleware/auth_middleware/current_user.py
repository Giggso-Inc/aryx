"""
FastAPI dependency-style helpers for resolving the current user from
request.state (populated by AuthMiddleware) plus an optional DB session.

Split out of app/middleware/auth_middleware.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

from typing import Optional

from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.invitation import Invitation


async def get_current_user(request: Request, db: Optional[AsyncSession] = None) -> Optional[User]:
    """Get current user from request state"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None

    # If database session is provided, use it
    if db:
        # Query user from database
        from sqlalchemy import select
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None

        return user

    # Fallback: Get database session (this should be avoided in most cases)
    async for db_session in get_db():
        # Query user from database
        from sqlalchemy import select
        stmt = select(User).where(User.id == user_id)
        result = await db_session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None

        return user


async def _user_has_used_invitation(user: User, db: AsyncSession) -> bool:
    """True if this user was created via a used invitation (email + company_id match)."""
    if not user.email_id or not user.company_id:
        return False
    stmt = select(Invitation).where(
        Invitation.email == user.email_id,
        Invitation.company_id == user.company_id,
        Invitation.status == "used",
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_current_user_required(request: Request, db: Optional[AsyncSession] = None) -> User:
    """Get current user, raise exception if not authenticated or not verified"""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Block app access until email is verified, unless user was invited (has used invitation)
    if not getattr(user, "is_verified", True):
        if db is not None:
            has_used_invitation = await _user_has_used_invitation(user, db)
        else:
            async for session in get_db():
                has_used_invitation = await _user_has_used_invitation(user, session)
                break
            else:
                has_used_invitation = False
        if has_used_invitation:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email to continue.",
        )
    return user


async def get_current_user_optional(request: Request, db: Optional[AsyncSession] = None) -> Optional[User]:
    """Get current user, return None if not authenticated"""
    return await get_current_user(request, db)
