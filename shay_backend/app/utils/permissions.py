"""
Scope-aware permission helpers.

Uses the unified gg_members table (exclusive arc pattern) to resolve the
most specific active role for a user across workspace / channel / thread scopes.

Inheritance direction: bottom-up (thread > channel > workspace).
The most specific active role wins.
"""

from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.member import GGMember


async def get_effective_role(
    db: AsyncSession,
    user_id: UUID,
    *,
    thread_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
) -> Optional[str]:
    """
    Resolve the most specific active role for a user.

    Resolution order: thread → channel → workspace (most specific wins).
    Returns the role string (e.g. 'admin', 'member') or None if no access
    at any level.
    """
    checks = []
    if thread_id:
        checks.append(("thread", "thread_id", thread_id))
    if channel_id:
        checks.append(("channel", "channel_id", channel_id))
    if workspace_id:
        checks.append(("workspace", "workspace_id", workspace_id))

    for level, fk_field, fk_value in checks:
        stmt = select(GGMember).where(
            and_(
                GGMember.user_id == user_id,
                GGMember.is_active == True,
                GGMember.level == level,
                getattr(GGMember, fk_field) == fk_value,
            )
        )
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()
        if member:
            return member.role

    return None  # No access at any level


async def require_effective_role(
    db: AsyncSession,
    user_id: UUID,
    *,
    thread_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    min_role: Optional[str] = None,
) -> str:
    """
    Like get_effective_role but raises HTTP 403 if the user has no access.
    Optionally checks that the resolved role matches min_role (e.g. 'admin').
    """
    role = await get_effective_role(
        db, user_id,
        thread_id=thread_id,
        channel_id=channel_id,
        workspace_id=workspace_id,
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You are not a member of this workspace/channel/thread.",
        )
    if min_role and role != min_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role. Required: {min_role}, current: {role}.",
        )
    return role


async def require_active_workspace_role(
    db: AsyncSession,
    user_id: UUID,
    workspace_id: UUID,
    *,
    allowed_roles: Optional[Iterable[str]] = None,
    access_detail: str = "Access denied to workspace",
    role_detail: str = "Only workspace admins can manage this workspace",
) -> str:
    """Require an active workspace membership, optionally constrained by role."""
    role = await get_effective_role(db, user_id, workspace_id=workspace_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=access_detail,
        )

    allowed = set(allowed_roles or [])
    if allowed and role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=role_detail,
        )

    return role
