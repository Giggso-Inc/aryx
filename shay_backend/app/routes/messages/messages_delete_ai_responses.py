"""
delete_message sub-step: delete AIResponse rows for the message being
deleted.

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_response import AIResponse
from app.models.message import Message


async def delete_ai_responses_for_message(db: AsyncSession, message: Message) -> List[AIResponse]:
    """Delete all AIResponse rows tied to this message; return the deleted rows."""
    ai_responses_stmt = select(AIResponse).where(AIResponse.message_id == message.id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()

    for ai_response in ai_responses:
        await db.delete(ai_response)

    return ai_responses
