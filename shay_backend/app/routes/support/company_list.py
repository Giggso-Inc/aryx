"""
GET /company/{company_id} -> list_support_requests_by_company.

Split from the original 288-line app/routes/support.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.support_request import SupportRequest
from app.schemas.support import SupportRequestListResponse

from .helpers import _support_detail_from_model, _can_access_company_support

router = APIRouter()


@router.get("/company/{company_id}", response_model=SupportRequestListResponse)
async def list_support_requests_by_company(
    company_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
) -> SupportRequestListResponse:
    """
    List support requests for a company. Requires authentication.
    User must belong to the company or be an admin.
    """
    user = await get_current_user_required(request, db)
    if not _can_access_company_support(user, company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to support requests for this company",
        )
    # Count total for this company
    count_stmt = select(func.count(SupportRequest.id)).where(
        SupportRequest.company_id == company_id
    )
    total = (await db.execute(count_stmt)).scalar() or 0
    # Paginate
    offset = (page - 1) * size
    pages = (total + size - 1) // size if size else 0
    stmt = (
        select(SupportRequest)
        .where(SupportRequest.company_id == company_id)
        .order_by(SupportRequest.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()
    items = [_support_detail_from_model(sr) for sr in requests]
    return SupportRequestListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=pages,
    )
