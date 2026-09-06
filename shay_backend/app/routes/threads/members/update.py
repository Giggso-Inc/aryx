"""
PUT /{thread_id}/members/{user_id} (update_thread_member) — mounted at
/api/v1/threads.

Split from app/routes/threads/members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.member import MemberUpdate, MemberResponse

from .serializers import member_to_response

router = APIRouter()


@router.put("/{thread_id}/members/{user_id}", response_model=MemberResponse)
async def update_thread_member(
    thread_id: str,
    user_id: str,
    member_data: MemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Update a thread-level member override."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
        u_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = select(GGMember).where(and_(
        GGMember.thread_id == t_uuid,
        GGMember.user_id == u_uuid,
        GGMember.level == "thread",
    ))
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Thread membership not found")

    for field, value in member_data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    return member_to_response(member)
