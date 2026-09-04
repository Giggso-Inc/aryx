"""
Workspace-level GGMember endpoints: list, add, update, remove members, and
resolve a user's effective role at thread/channel/workspace scope.

Split from app/routes/gg_workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.user import User
from app.services.email_service import email_service
from app.schemas.gg_workspace import (
    GGWorkspaceMemberCreate,
    GGWorkspaceMemberList,
    GGWorkspaceMemberResponse,
    GGWorkspaceMemberUpdate,
)
from app.utils.permissions import get_effective_role, require_active_workspace_role

from .helpers import _get_workspace_or_404, _member_resp, _to_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{workspace_id}/members", response_model=GGWorkspaceMemberList)
async def list_workspace_members(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
) -> GGWorkspaceMemberList:
    """List all GGMembers at workspace scope (level='workspace')."""
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    filters = [
        GGMember.workspace_id == ws_uuid,
        GGMember.level == "workspace",
    ]
    if role:
        filters.append(GGMember.role == role)
    filters.append(GGMember.is_active == (True if is_active is None else is_active))

    total = (await db.execute(
        select(func.count()).select_from(GGMember).where(and_(*filters))
    )).scalar()
    members = (await db.execute(
        select(GGMember).where(and_(*filters))
        .order_by(GGMember.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )).scalars().all()

    user_ids = [m.user_id for m in members]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
    } if user_ids else {}

    return GGWorkspaceMemberList(
        members=[_member_resp(m, users_by_id.get(m.user_id)) for m in members],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.post("/{workspace_id}/members", response_model=GGWorkspaceMemberResponse, status_code=201)
async def add_workspace_member(
    workspace_id: str,
    data: GGWorkspaceMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceMemberResponse:
    """Add a user to a workspace via GGMember (level='workspace')."""
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    ws = await _get_workspace_or_404(db, ws_uuid)

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        allowed_roles={"admin"},
        access_detail="Access denied to this workspace",
    )

    member = GGMember(
        id=uuid4(),
        user_id=data.user_id,
        workspace_id=ws_uuid,
        level="workspace",
        role=data.role,
        permissions=data.permissions or {},
        invited_by=data.invited_by or user.id,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a workspace membership.")
        raise

    try:
        added_user = (
            await db.execute(select(User).where(User.id == data.user_id))
        ).scalar_one_or_none()
        if added_user and added_user.email_id:
            inviter_display = (
                getattr(user, "name", None)
                or getattr(user, "email_id", None)
                or "A workspace administrator"
            )
            workspace_home_url = f"{settings.PLATFORM_URL.rstrip('/')}/workspaces/{ws.id}/home"
            await email_service.send_workspace_access_email(
                to_email=added_user.email_id,
                workspace_access_data={
                    "workspace_name": ws.name,
                    "user_name": added_user.name,
                    "role": data.role,
                    "added_by": inviter_display,
                    "platform_name": email_service.default_platform_name,
                    "support_email": settings.SUPPORT_EMAIL,
                },
                platform_url=workspace_home_url,
            )
        else:
            logger.warning(
                "Workspace member added without notification email: user=%s",
                data.user_id,
            )
    except Exception as email_error:
        logger.exception(
            "Error sending workspace member email (non-critical): %s",
            email_error,
        )

    return _member_resp(member)


@router.put("/{workspace_id}/members/{user_id}", response_model=GGWorkspaceMemberResponse)
async def update_workspace_member(
    workspace_id: str,
    user_id: str,
    data: GGWorkspaceMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceMemberResponse:
    """Update a workspace GGMember's role, permissions, or active status."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        allowed_roles={"admin"},
        access_detail="Access denied to this workspace",
    )
    if str(user.id) == str(user_uuid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own workspace membership",
        )

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.workspace_id == ws_uuid,
            GGMember.user_id      == user_uuid,
            GGMember.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Workspace membership not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    member_user = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none()
    return _member_resp(member, member_user)


@router.delete("/{workspace_id}/members/{user_id}", status_code=200)
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a GGMember from a workspace."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        allowed_roles={"admin"},
        access_detail="Access denied to this workspace",
    )
    if str(user.id) == str(user_uuid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own workspace membership",
        )

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.workspace_id == ws_uuid,
            GGMember.user_id      == user_uuid,
            GGMember.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Workspace membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Workspace member removed successfully"}


@router.get("/{workspace_id}/members/{user_id}/effective-role")
async def get_effective_role_endpoint(
    workspace_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = Query(None),
    thread_id:  Optional[str] = Query(None),
) -> dict:
    """
    Resolve the effective role for a user at the given scope.
    Resolution order: thread → channel → workspace (most specific wins).
    """
    await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    ch_uuid = _to_uuid(channel_id, "channel_id") if channel_id else None
    th_uuid = _to_uuid(thread_id,  "thread_id")  if thread_id  else None

    role = await get_effective_role(
        db,
        user_id=user_uuid,
        workspace_id=ws_uuid,
        channel_id=ch_uuid,
        thread_id=th_uuid,
    )

    return {
        "user_id":        user_id,
        "effective_role": role,
        "has_access":     role is not None,
        "resolved_at":    (
            "thread"    if th_uuid and role else
            "channel"   if ch_uuid and role else
            "workspace" if role else None
        ),
    }
