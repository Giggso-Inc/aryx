"""
POST /trigger/{message_id} -> trigger_ai_processing.

Split from the original 370-line app/routes/agent.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5). The
background-task helper it schedules, `process_ai_request`, lives in the
sibling `process_ai_request.py` to keep both files under the Raven 150-line
style limit.

PRE-EXISTING BUG preserved as-is (see tests/test_agent_characterization.py):
the 404 "Message not found" and 400 "AI processing already triggered" cases
are raised inside the try block and re-wrapped into a generic 500 by the
blanket `except Exception`.
"""

from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import generate_ai_response_id
from app.models.message import Message
from app.models.ai_response import AIResponse
from app.schemas.agent import AITrigger

from .process_ai_request import process_ai_request

router = APIRouter()


@router.post("/trigger/{message_id}")
async def trigger_ai_processing(
    message_id: str,
    trigger_data: AITrigger,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Manually trigger AI processing for a message"""
    try:
        # Get message
        stmt = select(Message).where(Message.id == message_id)
        result = await db.execute(stmt)
        message = result.scalar_one_or_none()

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        # Check if AI response already exists
        stmt = select(AIResponse).where(AIResponse.message_id == message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()

        if ai_response and not trigger_data.force_retry:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI processing already triggered for this message"
            )

        # Create or update AI response
        if not ai_response:
            ai_response = AIResponse(
                id=generate_ai_response_id(),
                message_id=message_id,
                thread_id=message.thread_id,
                workspace_id=message.workspace_id,
                ai_provider=trigger_data.ai_provider or "openai",
                ai_model=trigger_data.ai_model or "gpt-4",
                response_content="",
                status="pending"
            )
            db.add(ai_response)
        else:
            # Reset for retry
            ai_response.status = "pending"
            ai_response.error_message = None
            ai_response.retry_count += 1
            if trigger_data.ai_provider:
                ai_response.ai_provider = trigger_data.ai_provider
            if trigger_data.ai_model:
                ai_response.ai_model = trigger_data.ai_model

        await db.commit()

        # Trigger AI processing
        background_tasks.add_task(process_ai_request, message_id)

        return {"message": "AI processing triggered successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger AI processing: {str(e)}"
        )
