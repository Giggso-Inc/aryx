"""
POST /status -> ai_status_update.

Split from the original 370-line app/routes/agent.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.ai_response import AIResponse
from app.schemas.agent import AIStatus

router = APIRouter()


@router.post("/status")
async def ai_status_update(
    status_data: AIStatus,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Receive AI processing status update"""
    try:
        # Get AI response
        stmt = select(AIResponse).where(AIResponse.message_id == status_data.message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()

        if not ai_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI response not found"
            )

        # Update status
        ai_response.status = status_data.status
        ai_response.error_message = status_data.error_message
        ai_response.metadata = status_data.metadata

        await db.commit()

        return {"message": "AI status updated successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update AI status: {str(e)}"
        )
