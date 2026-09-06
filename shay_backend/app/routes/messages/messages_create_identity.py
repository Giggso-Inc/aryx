"""
create_message sub-step: resolve the effective user_id/query_id for a new
message, including system-message query_id validation.

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.message import Message
from app.schemas.message import MessageCreate
from .system_user import get_or_create_system_user


async def resolve_message_identity(
    db: AsyncSession,
    message_data: MessageCreate,
    user: User,
) -> Tuple[object, Optional[object]]:
    """
    Determine the user_id and query_id to store on a new message.

    For a "system" message, this substitutes the system user's id and
    validates that query_id references an existing "user" message in the
    same thread. For any other message type, the requesting user's own id
    is used and query_id is left unset.

    Returns:
        (user_id, query_id)
    """
    if message_data.message_type != "system":
        return user.id, None

    system_user = await get_or_create_system_user(db)
    user_id = system_user.id

    if not message_data.query_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query_id is required for system messages"
        )

    # Validate that the query message exists and is a user message
    query_stmt = select(Message).where(
        and_(
            Message.id == message_data.query_id,
            Message.thread_id == message_data.thread_id,
            Message.message_type == "user"
        )
    )
    query_result = await db.execute(query_stmt)
    query_message = query_result.scalar_one_or_none()

    if not query_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query message not found or invalid"
        )

    return user_id, message_data.query_id
