"""
GET/PUT/DELETE /{app_id} — get, update, and delete a single app.

Split from the original app/routes/apps.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.schemas.app import AppUpdate, AppResponse

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


@router.put("/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: str,
    app_data: AppUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppResponse:
    """Update an app"""
    user = await get_current_user_required(request)

    # Check if user has admin permissions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update apps"
        )

    # Get app
    app_stmt = select(App).where(App.id == app_id)
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found"
        )

    # Check for name or key conflict if being updated
    if app_data.app_name and app_data.app_name != app.app_name:
        existing_app_stmt = select(App).where(
            and_(
                App.app_name == app_data.app_name,
                App.id != app_id
            )
        )
        existing_app_result = await db.execute(existing_app_stmt)
        existing_app = existing_app_result.scalar_one_or_none()

        if existing_app:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="App with this name already exists"
            )

    if app_data.app_key and app_data.app_key != app.app_key:
        existing_app_stmt = select(App).where(
            and_(
                App.app_key == app_data.app_key,
                App.id != app_id
            )
        )
        existing_app_result = await db.execute(existing_app_stmt)
        existing_app = existing_app_result.scalar_one_or_none()

        if existing_app:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="App with this key already exists"
            )

    # Update app fields
    update_data = app_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    await db.commit()
    await db.refresh(app)

    return to_app_response(app)


@router.delete("/{app_id}")
async def delete_app(
    app_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete an app"""
    user = await get_current_user_required(request)

    # Check if user has admin permissions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete apps"
        )

    # Get app
    app_stmt = select(App).where(App.id == app_id)
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found"
        )

    # Delete app
    await db.delete(app)
    await db.commit()

    return {"message": "App deleted successfully"}
