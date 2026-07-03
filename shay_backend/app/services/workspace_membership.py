"""Helpers for keeping workspace memberships aligned with company access rules."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.member import GGMember
from app.models.user import User
from app.models.workspace import Workspace


def _default_role_for_user(user: User) -> str:
    return "admin" if user.role == "admin" else "member"


async def ensure_workspace_membership(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    role: str | None = None,
    invited_by: str | None = None,
) -> GGMember:
    """Ensure a user has an active workspace membership row."""
    membership = (
        await db.execute(
            select(GGMember).where(
                and_(
                    GGMember.workspace_id == workspace.id,
                    GGMember.user_id == user.id,
                    GGMember.level == "workspace",
                )
            )
        )
    ).scalar_one_or_none()

    expected_role = role or _default_role_for_user(user)
    if membership:
        changed = False
        if not membership.is_active:
            membership.is_active = True
            changed = True
        if membership.role != expected_role:
            membership.role = expected_role
            changed = True
        if membership.joined_at is None:
            membership.joined_at = datetime.utcnow()
            changed = True
        if changed:
            await db.flush()
        return membership

    membership = GGMember(
        id=uuid4(),
        user_id=user.id,
        workspace_id=workspace.id,
        level="workspace",
        role=expected_role,
        is_active=True,
        permissions={},
        invited_by=invited_by or workspace.created_by or user.id,
        joined_at=datetime.utcnow(),
    )
    db.add(membership)
    await db.flush()
    return membership


async def ensure_default_workspace_memberships(
    db: AsyncSession,
    *,
    workspace: Workspace,
) -> int:
    """
    Backfill memberships for the company's default workspace.

    The default company workspace is the one created with the same name as the
    company itself during company signup / invitation flows. Every active user in
    the company should have a workspace membership row there so workspace settings
    and access views stay consistent.
    """
    company = (
        await db.execute(select(Company).where(Company.id == workspace.company_id))
    ).scalar_one_or_none()
    if not company or workspace.name != company.name:
        return 0

    users = (
        await db.execute(
            select(User).where(
                and_(
                    User.company_id == workspace.company_id,
                    User.is_active == True,  # noqa: E712
                )
            )
        )
    ).scalars().all()

    changes = 0
    for user in users:
        existing = (
            await db.execute(
                select(GGMember).where(
                    and_(
                        GGMember.workspace_id == workspace.id,
                        GGMember.user_id == user.id,
                        GGMember.level == "workspace",
                    )
                )
            )
        ).scalar_one_or_none()
        expected_role = _default_role_for_user(user)
        membership = await ensure_workspace_membership(
            db,
            workspace=workspace,
            user=user,
        )
        if (
            existing is None
            or not existing.is_active
            or existing.role != expected_role
            or existing.joined_at is None
        ):
            changes += 1

    if changes:
        await db.flush()
    return changes
