"""
GET / — list_apps.

Split from the original app/routes/apps.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.schemas.app import AppList

from .common import CLOUD_DRIVE_APP_KEYS, EXCLUDED_APP_KEYS, to_app_response

router = APIRouter()


@router.get("/", response_model=AppList)
async def list_apps(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    subCategory: Optional[str] = Query(None, description="Filter by subcategory: 'Cloud Drive' or 'Datasource' (case-insensitive)"),
    is_active: Optional[bool] = None,
    is_public: Optional[bool] = None
) -> AppList:
    """List available apps with filtering and pagination"""
    user = await get_current_user_required(request)

    # Build query
    query = select(App)

    # Apply filters
    filters = []

    # Exclude apps that should not be shown in the API (but kept in DB for referential integrity)
    if EXCLUDED_APP_KEYS:
        excluded_filter = and_(*[func.lower(App.app_key) != func.lower(key)
                                for key in EXCLUDED_APP_KEYS])
        filters.append(excluded_filter)

    if search:
        search_filter = or_(
            App.app_name.ilike(f"%{search}%"),
            App.app_key.ilike(f"%{search}%"),
            App.app_description.ilike(f"%{search}%"),
            App.category.ilike(f"%{search}%")
        )
        filters.append(search_filter)

    if category:
        filters.append(App.category == category)

    if subCategory:
        # Case-insensitive filtering for subCategory based on app_key
        sub_category_lower = subCategory.lower()
        if sub_category_lower == 'cloud drive':
            # Filter for Cloud Drive apps
            cloud_drive_filter = or_(*[func.lower(App.app_key) == func.lower(key)
                                      for key in CLOUD_DRIVE_APP_KEYS])
            filters.append(cloud_drive_filter)
        elif sub_category_lower == 'datasource':
            # Filter for Datasource apps (exclude Cloud Drive apps)
            datasource_filter = and_(*[func.lower(App.app_key) != func.lower(key)
                                      for key in CLOUD_DRIVE_APP_KEYS])
            filters.append(datasource_filter)

    if is_active is not None:
        filters.append(App.is_active == is_active)

    if is_public is not None:
        filters.append(App.is_public == is_public)

    # Apply filters to query
    if filters:
        query = query.where(and_(*filters))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Sort by is_active (True values first, then False), then by app_name alphabetically
    query = query.order_by(App.is_active.desc(), App.app_name.asc())

    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    apps = result.scalars().all()

    # Calculate pagination info
    pages = (total + size - 1) // size

    return AppList(
        apps=[to_app_response(app) for app in apps],
        total=total,
        page=page,
        size=size,
        pages=pages
    )
