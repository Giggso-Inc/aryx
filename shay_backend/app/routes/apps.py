"""
App routes for CRUD operations to manage available applications
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
import uuid

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.app import App
from app.schemas.app import (
    AppCreate,
    AppUpdate,
    AppResponse,
    AppList,
    AppStats,
    AppCategoryListResponse
)

router = APIRouter()
security = HTTPBearer()

# Cloud Drive app keys (for sub_category filtering)
CLOUD_DRIVE_APP_KEYS = ['google_drive', 'googledrive', 'sharepoint', 'share_point', 
                        'dropbox', 'onedrive', 'one_drive', 'box']

# App keys to exclude from list_apps API (kept in DB for foreign key integrity)
EXCLUDED_APP_KEYS = settings.EXCLUDED_APP_KEYS.split(",")


@router.post("/", response_model=AppResponse)
async def create_app(
    app_data: AppCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
    
    return AppResponse(
        id=str(app.id),
        app_name=app.app_name,
        app_key=app.app_key,
        app_description=app.app_description,
        app_image=app.app_image,
        is_active=app.is_active,
        is_public=app.is_public,
        version=app.version,
        category=app.category,
        sub_category=app.sub_category,
        tags=app.tags,
        created_at=app.created_at,
        updated_at=app.updated_at
    )


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
):
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
        apps=[AppResponse(
            id=str(app.id),
            app_name=app.app_name,
            app_key=app.app_key,
            app_description=app.app_description,
            app_image=app.app_image,
            is_active=app.is_active,
            is_public=app.is_public,
            version=app.version,
            category=app.category,
            sub_category=app.sub_category,
            tags=app.tags,
            created_at=app.created_at,
            updated_at=app.updated_at
        ) for app in apps],
        total=total,
        page=page,
        size=size,
        pages=pages
    )


@router.get("/categories", response_model=AppCategoryListResponse)
async def get_app_categories(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
):
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
        recent_apps=[AppResponse(
            id=str(app.id),
            app_name=app.app_name,
            app_key=app.app_key,
            app_description=app.app_description,
            app_image=app.app_image,
            is_active=app.is_active,
            is_public=app.is_public,
            version=app.version,
            category=app.category,
            sub_category=app.sub_category,
            tags=app.tags,
            created_at=app.created_at,
            updated_at=app.updated_at
        ) for app in recent_apps]
    )


@router.get("/{app_id}", response_model=AppResponse)
async def get_app(
    app_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
    
    return AppResponse(
        id=str(app.id),
        app_name=app.app_name,
        app_key=app.app_key,
        app_description=app.app_description,
        app_image=app.app_image,
        is_active=app.is_active,
        is_public=app.is_public,
        version=app.version,
        category=app.category,
        sub_category=app.sub_category,
        tags=app.tags,
        created_at=app.created_at,
        updated_at=app.updated_at
    )


@router.put("/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: str,
    app_data: AppUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
    
    return AppResponse(
        id=str(app.id),
        app_name=app.app_name,
        app_key=app.app_key,
        app_description=app.app_description,
        app_image=app.app_image,
        is_active=app.is_active,
        is_public=app.is_public,
        version=app.version,
        category=app.category,
        sub_category=app.sub_category,
        tags=app.tags,
        created_at=app.created_at,
        updated_at=app.updated_at
    )


@router.delete("/{app_id}")
async def delete_app(
    app_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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