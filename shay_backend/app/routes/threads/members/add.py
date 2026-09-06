"""
POST /{thread_id}/members (add_thread_member) — mounted at /api/v1/threads.

Split from app/routes/threads/members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.member import MemberCreate, MemberResponse

from .serializers import member_to_response

router = APIRouter()


@router.post("/{thread_id}/members", response_model=MemberResponse, status_code=201)
async def add_thread_member(
    thread_id: str,
    member_data: MemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Add (or override) a user's role at thread level."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    if member_data.level != "thread" or str(member_data.thread_id) != thread_id:
        raise HTTPException(
            status_code=422,
            detail="level must be 'thread' and thread_id in body must match the URL param",
        )

    member = GGMember(
        id=uuid4(),
        user_id=member_data.user_id,
        thread_id=t_uuid,
        level="thread",
        role=member_data.role,
        permissions=member_data.permissions or {},
        invited_by=member_data.invited_by,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a thread-level membership.")
        raise

    return member_to_response(member)
