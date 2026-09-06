"""
GET /{workspace_id}/members (list_workspace_members) — mounted at
/api/v1/gg-workspaces.

Split from app/routes/gg_workspaces/members.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.user import User
from app.schemas.gg_workspace import GGWorkspaceMemberList
from app.utils.permissions import require_active_workspace_role

from ..helpers import _get_workspace_or_404, _member_resp, _to_uuid

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
