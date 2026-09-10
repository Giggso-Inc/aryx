"""
POST /threads/move — move_thread: move a thread between two regular
(message-type) channels in the same workspace.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2: validation and the cross-table cascade update split into
threads_move_validation.py and threads_move_cascade.py. What stays here is
the single transaction boundary — cascade + audit log must commit or roll
back together, so that stays one try/except in the orchestrator.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.schemas.message import ThreadMoveRequest, ThreadMoveResponse
from .threads_move_validation import (
    load_thread_for_move,
    load_and_validate_move_channels,
    check_move_permission,
    check_thread_movable,
)
from .threads_move_cascade import apply_thread_move_cascade

router = APIRouter()


@router.post("/threads/move", response_model=ThreadMoveResponse)
async def move_thread(
    payload: ThreadMoveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadMoveResponse:
    """
    Move a thread from one regular channel to another. Both channels must be
    message-type; validations include same workspace and active thread.
    """
    # Require authenticated user (avoids Depends(get_current_user) which triggers FastAPI response-field error on AsyncSession)
    user = await get_current_user_required(request, db)

    thread_id = payload.thread_id
    new_channel_id = payload.new_channel_id

    thread = await load_thread_for_move(db, thread_id, new_channel_id)
    old_channel_id = thread.channel_id

    source_channel, _dest_channel = await load_and_validate_move_channels(
        db, old_channel_id, new_channel_id
    )
    check_move_permission(source_channel, user)
    check_thread_movable(thread)

    try:
        updated_counts = await apply_thread_move_cascade(db, thread_id, old_channel_id, new_channel_id)

        await audit_log_write(
            db, user.id, "thread.moved", "thread", thread.id,
            channel_id=new_channel_id, thread_id=thread.id,
            details={"old_channel_id": str(old_channel_id), "new_channel_id": str(new_channel_id)},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return ThreadMoveResponse(
        thread_id=payload.thread_id,
        old_channel_id=old_channel_id,
        new_channel_id=payload.new_channel_id,
        updated_counts=updated_counts,
    )
