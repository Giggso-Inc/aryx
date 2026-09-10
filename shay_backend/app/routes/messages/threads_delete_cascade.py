"""
delete_thread sub-steps: delete a thread's messages and AI responses.

Split out of app/routes/messages/threads_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.ai_response import AIResponse


async def delete_thread_messages(db: AsyncSession, thread_id: str) -> int:
    """Delete every message in a thread so they don't point at a missing thread.

    Returns the count of messages deleted.
    """
    delete_messages_stmt = select(Message).where(Message.thread_id == thread_id)
    messages_result = await db.execute(delete_messages_stmt)
    messages = messages_result.scalars().all()
    for message in messages:
        await db.delete(message)
    return len(messages)


async def delete_thread_ai_responses(db: AsyncSession, thread_id: str) -> List[AIResponse]:
    """Delete all AIResponse rows tied to this thread; return the deleted rows."""
    ai_responses_stmt = select(AIResponse).where(AIResponse.thread_id == thread_id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()
    for ai_response in ai_responses:
        await db.delete(ai_response)
    return ai_responses
