"""
POST /callback -> ai_callback.

Split from the original 370-line app/routes/agent.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).

PRE-EXISTING BUG preserved as-is (see tests/test_agent_characterization.py
for the full writeup): no auth dependency at all, and the try/except
Exception wraps re-raise deliberately-raised HTTPExceptions (404) into a
generic 500.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import generate_ai_response_id
from app.models.message import Message
from app.models.ai_response import AIResponse
from app.schemas.agent import AICallback

router = APIRouter()


@router.post("/callback")
async def ai_callback(
    callback_data: AICallback,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Receive AI processing callback"""
    try:
        # Get message
        stmt = select(Message).where(Message.id == callback_data.message_id)
        result = await db.execute(stmt)
        message = result.scalar_one_or_none()

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        # Get or create AI response
        stmt = select(AIResponse).where(AIResponse.message_id == callback_data.message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()

        if not ai_response:
            ai_response = AIResponse(
                id=generate_ai_response_id(),
                message_id=callback_data.message_id,
                thread_id=callback_data.thread_id,
                workspace_id=callback_data.workspace_id,
                ai_provider=callback_data.ai_provider,
                ai_model=callback_data.ai_model,
                response_content=callback_data.response_content,
                response_type=callback_data.response_type,
                confidence_score=callback_data.confidence_score,
                relevance_score=callback_data.relevance_score,
                processing_time_ms=callback_data.processing_time_ms,
                status=callback_data.status,
                error_message=callback_data.error_message,
                metadata=callback_data.metadata,
                tags=callback_data.tags,
                processed_at=datetime.utcnow() if callback_data.status == "completed" else None
            )
            db.add(ai_response)
        else:
            # Update existing AI response
            ai_response.response_content = callback_data.response_content
            ai_response.response_type = callback_data.response_type
            ai_response.confidence_score = callback_data.confidence_score
            ai_response.relevance_score = callback_data.relevance_score
            ai_response.processing_time_ms = callback_data.processing_time_ms
            ai_response.status = callback_data.status
            ai_response.error_message = callback_data.error_message
            ai_response.metadata = callback_data.metadata
            ai_response.tags = callback_data.tags
            ai_response.processed_at = datetime.utcnow() if callback_data.status == "completed" else None

        # Update message with AI processing info
        message.is_ai_processed = True
        message.ai_provider = callback_data.ai_provider
        message.ai_model = callback_data.ai_model
        message.ai_processing_time = callback_data.processing_time_ms

        await db.commit()

        return {"message": "AI callback processed successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process AI callback: {str(e)}"
        )
