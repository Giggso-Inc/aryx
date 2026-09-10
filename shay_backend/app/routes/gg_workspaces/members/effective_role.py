"""
GET /{workspace_id}/members/{user_id}/effective-role
(get_effective_role_endpoint) — mounted at /api/v1/gg-workspaces.

Split from app/routes/gg_workspaces/members.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.utils.permissions import get_effective_role

from ..helpers import _to_uuid

router = APIRouter()


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
