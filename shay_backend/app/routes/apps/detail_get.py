"""
GET /{app_id} — get_app.

Split from the original app/routes/apps.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2; further
split in wave B4 out of detail.py, one endpoint per file).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.schemas.app import AppResponse
from .common import to_app_response

router = APIRouter()


@router.get("/{app_id}", response_model=AppResponse)
async def get_app(
    app_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppResponse:
    """Get a specific app by ID"""
    user = await get_current_user_required(request)

    # Get app
    app_stmt = select(App).where(App.id == app_id)
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found"
        )

    # Check if user can access this app
    if not app.is_public and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app"
        )

    return to_app_response(app)
