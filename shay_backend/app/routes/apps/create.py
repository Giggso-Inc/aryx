"""
POST / — create_app.

Split from the original app/routes/apps.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
import uuid

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.schemas.app import AppCreate, AppResponse

from .common import to_app_response

router = APIRouter()


@router.post("/", response_model=AppResponse)
async def create_app(
    app_data: AppCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppResponse:
    """Create a new app"""
    user = await get_current_user_required(request)

    # Check if user has admin permissions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create apps"
        )

    # Check if app with same name or key already exists
    existing_app_stmt = select(App).where(
        or_(
            App.app_name == app_data.app_name,
            App.app_key == app_data.app_key
        )
    )
    existing_app_result = await db.execute(existing_app_stmt)
    existing_app = existing_app_result.scalar_one_or_none()

    if existing_app:
        if existing_app.app_name == app_data.app_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="App with this name already exists"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="App with this key already exists"
            )

    # Create app
    app = App(
        id=str(uuid.uuid4()),
        app_name=app_data.app_name,
        app_key=app_data.app_key,
        app_description=app_data.app_description,
        app_image=app_data.app_image,
        is_active=app_data.is_active,
        is_public=app_data.is_public,
        version=app_data.version,
        category=app_data.category,
        tags=app_data.tags
    )

    db.add(app)
    await db.commit()
    await db.refresh(app)

    return to_app_response(app)
