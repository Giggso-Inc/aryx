"""
GET /categories and GET /stats — app category listing and aggregate stats.

Split from the original app/routes/apps.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

These two static-path endpoints must be registered before the dynamic
GET /{app_id} route (see the detail submodule) — preserved via the package
__init__'s registration order.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.schemas.app import AppStats, AppCategoryListResponse

from .common import to_app_response

router = APIRouter()


@router.get("/categories", response_model=AppCategoryListResponse)
async def get_app_categories(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppCategoryListResponse:
    """Get list of available app categories"""
    user = await get_current_user_required(request)

    # Get all distinct categories
    query = select(App.category).where(App.category.isnot(None)).distinct()

    # Execute query
    result = await db.execute(query)
    categories = [row[0] for row in result.fetchall() if row[0]]
    categories = sorted(categories)  # Sort alphabetically

    return AppCategoryListResponse(
        categories=categories,
        total=len(categories)
    )


@router.get("/stats", response_model=AppStats)
async def get_app_stats(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppStats:
    """Get app statistics"""
    user = await get_current_user_required(request)

    # Get total apps
    total_apps_query = select(func.count(App.id))
    total_apps_result = await db.execute(total_apps_query)
    total_apps = total_apps_result.scalar()

    # Get active apps
    active_apps_query = select(func.count(App.id)).where(App.is_active == True)
    active_apps_result = await db.execute(active_apps_query)
    active_apps = active_apps_result.scalar()

    # Get public apps
    public_apps_query = select(func.count(App.id)).where(App.is_public == True)
    public_apps_result = await db.execute(public_apps_query)
    public_apps = public_apps_result.scalar()

    # Get unique categories
    categories_query = select(App.category).where(App.category.isnot(None)).distinct()
    categories_result = await db.execute(categories_query)
    categories = [row[0] for row in categories_result.fetchall()]

    # Get recent apps
    recent_apps_query = select(App).order_by(App.created_at.desc()).limit(5)
    recent_apps_result = await db.execute(recent_apps_query)
    recent_apps = recent_apps_result.scalars().all()

    return AppStats(
        total_apps=total_apps,
        active_apps=active_apps,
        public_apps=public_apps,
        categories=categories,
        recent_apps=[to_app_response(app) for app in recent_apps]
    )
