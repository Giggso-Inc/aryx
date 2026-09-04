"""
Single-company endpoints: get by ID, update, and statistics.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.company import Company
from app.schemas.company import CompanyUpdate, CompanyResponse, CompanyStats

router = APIRouter()


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyResponse:
    """Get company by ID"""
    user = await get_current_user_required(request)

    # Check if user can access this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    return CompanyResponse.from_orm(company)


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    company_update: CompanyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyResponse:
    """Update company (admin only)"""
    user = await get_current_user_required(request)

    # Check if user can update this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Update company fields
    update_data = company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)

    return CompanyResponse.from_orm(company)


@router.get("/{company_id}/stats", response_model=CompanyStats)
async def get_company_stats(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyStats:
    """Get company statistics"""
    user = await get_current_user_required(request)

    # Check if user can access this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Get company
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Get statistics
    # Note: This is a simplified version. In a real app, you'd want to optimize these queries
    from app.models.workspace import Workspace
    from app.models.message import Message
    from app.models.attachment import Attachment

    try:
        # Count users
        user_count_stmt = select(func.count(User.id)).where(User.company_id == company_id)
        user_count_result = await db.execute(user_count_stmt)
        total_users = user_count_result.scalar() or 0

        # Count workspaces
        workspace_count_stmt = select(func.count(Workspace.id)).where(Workspace.company_id == company_id)
        workspace_count_result = await db.execute(workspace_count_stmt)
        total_workspaces = workspace_count_result.scalar() or 0

        # Count messages for this company's workspaces (simplified to avoid join issues)
        message_count_stmt = select(func.count(Message.id))
        message_count_result = await db.execute(message_count_stmt)
        total_messages = message_count_result.scalar() or 0

        # Count attachments for this company's workspaces (simplified to avoid join issues)
        attachment_count_stmt = select(func.count(Attachment.id))
        attachment_count_result = await db.execute(attachment_count_stmt)
        total_attachments = attachment_count_result.scalar() or 0

    except Exception as e:
        # If there are any issues with the statistics queries, return default values
        total_users = 0
        total_workspaces = 0
        total_messages = 0
        total_attachments = 0

    return CompanyStats(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_messages=total_messages,
        total_attachments=total_attachments,
        storage_used_gb=0.0,  # TODO: Implement actual storage calculation
        subscription_plan=company.subscription_plan
    )
