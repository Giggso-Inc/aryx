"""
PUT /{workspace_id}/members/{user_id} (update_workspace_member) — mounted
at /api/v1/gg-workspaces.

Split from app/routes/gg_workspaces/members.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.user import User
from app.schemas.gg_workspace import GGWorkspaceMemberResponse, GGWorkspaceMemberUpdate
from app.utils.permissions import require_active_workspace_role

from ..helpers import _member_resp, _to_uuid

router = APIRouter()


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
