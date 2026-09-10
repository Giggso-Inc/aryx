"""
GET /health -> ai_health_check.

Split from the original 370-line app/routes/agent.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5).
"""

from datetime import datetime

from fastapi import APIRouter
from app.schemas.agent import AIHealth

router = APIRouter()


@router.get("/health", response_model=AIHealth)
async def ai_health_check() -> AIHealth:
    """Check AI agent health"""
    try:
        # Simple health check - in a real implementation, you might check actual AI services
        return AIHealth(
            status="healthy",
            provider="openai",
            model="gpt-4",
            response_time_ms=100,
            last_check=datetime.utcnow(),
            error_count=0,
            success_rate=0.95
        )
    except Exception as e:
        return AIHealth(
            status="unhealthy",
            provider="unknown",
            model="unknown",
            last_check=datetime.utcnow(),
            error_count=1,
            success_rate=0.0
        )
