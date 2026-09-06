"""
POST /{workspace_id}/members (add_workspace_member) — mounted at
/api/v1/gg-workspaces.

Split from app/routes/gg_workspaces/members.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.user import User
from app.services.email_service import email_service
from app.schemas.gg_workspace import GGWorkspaceMemberCreate, GGWorkspaceMemberResponse
from app.utils.permissions import require_active_workspace_role

from ..helpers import _get_workspace_or_404, _member_resp, _to_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


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
