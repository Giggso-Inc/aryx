"""
GET /{thread_id}/members (list_thread_members) — mounted at /api/v1/threads.

Split from app/routes/threads/members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.member import MemberList

from .serializers import member_to_response

router = APIRouter()


@router.get("/{thread_id}/members", response_model=MemberList)
async def list_thread_members(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> MemberList:
    """List thread-level member overrides (level='thread' only)."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    offset = (page - 1) * size
    stmt = (
        select(GGMember)
        .where(and_(GGMember.thread_id == t_uuid, GGMember.level == "thread"))
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    members = result.scalars().all()

    count_stmt = select(func.count(GGMember.id)).where(
        and_(GGMember.thread_id == t_uuid, GGMember.level == "thread")
    )
    total = (await db.execute(count_stmt)).scalar()

    return MemberList(
        members=[member_to_response(m) for m in members],
        total=total,
        page=page,
        size=size,
    )
