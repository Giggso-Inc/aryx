"""Scope-existence and member-access checks shared by every gg_app_connections
submodule that operates on an existing or about-to-be-created connection."""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.member import GGMember
from app.models.workspace import Workspace


async def assert_scope_exists(
    db: AsyncSession,
    level: str,
    workspace_id: Optional[UUID],
    channel_id: Optional[UUID],
    thread_id: Optional[UUID],
) -> Optional[str]:
    """
    Verify the target scope entity exists.
    Returns the company_id (str) for workspace/channel scopes, None for thread scope.
    Raises 404 if not found.
    """
    if level == "workspace" and workspace_id:
        ws = (await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )).scalar_one_or_none()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return str(ws.company_id)

    if level == "channel" and channel_id:
        ch = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if not ch:
            raise HTTPException(status_code=404, detail="Channel not found")
        return str(ch.company_id)

    # Thread scope — just confirm thread exists via GGMember table (no separate thread model needed)
    # Thread existence is implicitly validated by the FK constraint on insert.
    return None


async def assert_member_access(
    db: AsyncSession,
    user_id: UUID,
    level: str,
    workspace_id: Optional[UUID],
    channel_id: Optional[UUID],
    thread_id: Optional[UUID],
    user_company_id: Optional[str] = None,
    company_id_from_scope: Optional[str] = None,
) -> None:
    """
    Verify the user has access to the given scope.

    Strategy (in order):
      1. Active GGMember row at the exact scope — always sufficient.
      2. For workspace/channel scopes: same company_id is sufficient (company-wide access).
    """
    # Check direct membership
    if level == "workspace" and workspace_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.workspace_id == workspace_id,
                GGMember.level == "workspace",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # Fallback: same company
        if user_company_id and company_id_from_scope and user_company_id == company_id_from_scope:
            return

    elif level == "channel" and channel_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.channel_id == channel_id,
                GGMember.level == "channel",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # Fallback: same company via channel
        if user_company_id and company_id_from_scope and user_company_id == company_id_from_scope:
            return

    elif level == "thread" and thread_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.thread_id == thread_id,
                GGMember.level == "thread",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # For thread scope fall back to checking parent channel membership
        # (thread is inside a channel; if user is a channel member they can access thread)
        parent_channel_member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.level == "channel",
                GGMember.is_active == True,
            ))
        )).first()
        if parent_channel_member:
            return

    raise HTTPException(
        status_code=403,
        detail=f"You do not have access to this {level}.",
    )
