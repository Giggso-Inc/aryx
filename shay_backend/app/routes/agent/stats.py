"""
GET /stats -> ai_stats.

Split from the original 370-line app/routes/agent.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.ai_response import AIResponse
from app.schemas.agent import AIStats

router = APIRouter()


@router.get("/stats", response_model=AIStats)
async def ai_stats(db: AsyncSession = Depends(get_db)) -> AIStats:
    """Get AI processing statistics"""
    try:
        # Get total requests
        total_query = select(func.count(AIResponse.id))
        total_result = await db.execute(total_query)
        total_requests = total_result.scalar()

        # Get successful requests
        success_query = select(func.count(AIResponse.id)).where(AIResponse.status == "completed")
        success_result = await db.execute(success_query)
        successful_requests = success_result.scalar()

        # Get failed requests
        failed_query = select(func.count(AIResponse.id)).where(AIResponse.status == "failed")
        failed_result = await db.execute(failed_query)
        failed_requests = failed_result.scalar()

        # Get average response time
        time_query = select(func.avg(AIResponse.processing_time_ms)).where(AIResponse.processing_time_ms.isnot(None))
        time_result = await db.execute(time_query)
        avg_response_time = time_result.scalar() or 0

        # Get total processing time
        total_time_query = select(func.sum(AIResponse.processing_time_ms)).where(AIResponse.processing_time_ms.isnot(None))
        total_time_result = await db.execute(total_time_query)
        total_processing_time = total_time_result.scalar() or 0

        # Get requests by time period (simplified)
        today_query = select(func.count(AIResponse.id)).where(
            AIResponse.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        today_result = await db.execute(today_query)
        requests_today = today_result.scalar()

        # Get top providers
        provider_query = select(
            AIResponse.ai_provider,
            func.count(AIResponse.id).label('count')
        ).group_by(AIResponse.ai_provider).order_by(func.count(AIResponse.id).desc()).limit(5)
        provider_result = await db.execute(provider_query)
        top_providers = [{"provider": row.ai_provider, "count": row.count} for row in provider_result]

        # Get top models
        model_query = select(
            AIResponse.ai_model,
            func.count(AIResponse.id).label('count')
        ).group_by(AIResponse.ai_model).order_by(func.count(AIResponse.id).desc()).limit(5)
        model_result = await db.execute(model_query)
        top_models = [{"model": row.ai_model, "count": row.count} for row in model_result]

        return AIStats(
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            average_response_time_ms=float(avg_response_time),
            total_processing_time_ms=int(total_processing_time),
            requests_today=requests_today,
            requests_this_week=requests_today,  # Simplified
            requests_this_month=requests_today,  # Simplified
            top_providers=top_providers,
            top_models=top_models
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get AI stats: {str(e)}"
        )
