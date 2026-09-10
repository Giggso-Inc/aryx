"""
Database template-record listing (for the "Database template management"
area — not filesystem-backed, unlike the /files/* endpoints above):

  GET    /
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.template import Template
from app.schemas.template import TemplateListResponse, TemplateResponse

router = APIRouter()


@router.get("/", response_model=TemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    is_active: Optional[str] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search in template name"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TemplateListResponse:
    """
    List template database records with pagination and filtering.

    Args:
        page: Page number
        size: Number of items per page
        is_active: Filter by active status
        search: Search query
        request: FastAPI request object
        db: Database session

    Returns:
        Paginated list of template records
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Build query
        query = select(Template)

        # Apply filters
        if is_active:
            query = query.where(Template.is_active == is_active)

        if search:
            query = query.where(
                or_(
                    Template.template_name.ilike(f"%{search}%"),
                    Template.template_id.ilike(f"%{search}%")
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        offset = (page - 1) * size
        query = query.offset(offset).limit(size).order_by(Template.created_datetime.desc())

        # Execute query
        result = await db.execute(query)
        templates = result.scalars().all()

        # Calculate pages
        pages = (total + size - 1) // size

        return TemplateListResponse(
            templates=[TemplateResponse.model_validate(t) for t in templates],
            total=total,
            page=page,
            size=size,
            pages=pages
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing templates: {str(e)}"
        )
