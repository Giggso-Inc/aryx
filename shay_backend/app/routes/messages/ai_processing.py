"""
AI-processing trigger, run as a background task from create_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.auth import generate_message_id
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.message import Message, Thread
from app.models.ai_response import AIResponse


async def trigger_ai_processing(message_id: str) -> None:
    """Trigger AI processing for a message"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get message
            stmt = select(Message).where(Message.id == message_id)
            result = await db.execute(stmt)
            message = result.scalar_one_or_none()

            if not message:
                return

            # Get thread to derive channel
            stmt = select(Thread).where(Thread.id == message.thread_id)
            result = await db.execute(stmt)
            ai_thread = result.scalar_one_or_none()
            if not ai_thread:
                return

            # Get channel
            stmt = select(Channel).where(Channel.id == ai_thread.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()

            if not channel or not channel.ai_enabled:
                return

            # Get workspace for AI settings
            stmt = select(Workspace).where(Workspace.id == channel.workspace_id)
            result = await db.execute(stmt)
            workspace = result.scalar_one_or_none()

            if not workspace:
                return

            # Create AI response record
            ai_response = AIResponse(
                id=generate_message_id(),  # Reusing message ID generator
                message_id=message_id,
                thread_id=message.thread_id,
                workspace_id=workspace.id,
                ai_provider=workspace.ai_provider,
                ai_model=workspace.ai_model,
                response_content="",  # Will be filled by AI callback
                status="pending"
            )

            db.add(ai_response)
            await db.commit()

            # TODO: Implement actual AI webhook call
            # For now, we'll just simulate the process

        except Exception as e:
            print(f"Error triggering AI processing: {e}")
            # Update AI response with error
            stmt = select(AIResponse).where(AIResponse.message_id == message_id)
            result = await db.execute(stmt)
            ai_response = result.scalar_one_or_none()

            if ai_response:
                ai_response.status = "failed"
                ai_response.error_message = str(e)
                await db.commit()
