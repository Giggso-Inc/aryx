"""
DELETE /{task_id} endpoint (mounted at /api/v1/tasks): delete_task.

Split out of the former crud.py (part of the Phase 5a item 2 follow-up that
lowered the per-file target to 150 lines).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message

router = APIRouter()


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a task"""
    user = await get_current_user_required(request, db)

    # Get task
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access through message -> channel membership
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == msg.channel_id,
                    ChannelMember.user_id == user.id,
                    ChannelMember.is_active == True
                )
            )
            channel_member_result = await db.execute(channel_member_stmt)
            channel_member = channel_member_result.scalar_one_or_none()
            if not channel_member and str(task.created_by) != str(user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to task"
                )

    # Delete task

    await audit_log_write(db, user.id, "task.deleted", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.delete(task)
    await db.commit()

    return {"message": "Task deleted successfully"}
