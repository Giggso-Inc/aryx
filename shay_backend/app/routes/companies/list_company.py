"""
Company listing and self-lookup endpoints: a dev/debug models check, the
admin-only company list, and the current user's own company.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.company import CompanyResponse, CompanyList

router = APIRouter()


@router.get("/test", response_model=dict)
async def test_models() -> dict:
    """Test endpoint to check if models are working"""
    try:
        from app.models.workspace import Workspace
        from app.models.message import Message
        from app.models.attachment import Attachment
        return {"status": "success", "message": "Models imported successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/", response_model=CompanyList)
async def list_companies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None
) -> CompanyList:
    """List companies (admin only)"""
    user = await get_current_user_required(request)

    # Only admins can list all companies
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can list all companies"
        )

    # Build query
    query = select(Company)

    if search:
        query = query.where(
            Company.name.ilike(f"%{search}%") |
            Company.domain.ilike(f"%{search}%")
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Pagination
    query = query.offset((page - 1) * size).limit(size)

    # Execute query
    result = await db.execute(query)
    companies = result.scalars().all()

    return CompanyList(
        companies=[CompanyResponse.from_orm(company) for company in companies],
        total=total,
        page=page,
        size=size
    )


@router.get("/my", response_model=CompanyResponse)
async def get_my_company(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyResponse:
    """Get current user's company"""
    user = await get_current_user_required(request)

    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with any company"
        )

    stmt = select(Company).where(Company.id == user.company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    return CompanyResponse.from_orm(company)
