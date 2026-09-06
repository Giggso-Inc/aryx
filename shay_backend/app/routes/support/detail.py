"""
GET/PUT/DELETE /{request_id} -> get_support_request, update_support_request,
delete_support_request.

Split from the original 288-line app/routes/support.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.support_request import SupportRequest
from app.schemas.support import (
    SupportRequestUpdate,
    SupportRequestDetail,
    SupportRequestDeleteResponse,
)

from .helpers import _support_detail_from_model, _can_access_support_request

router = APIRouter()


@router.get("/{request_id}", response_model=SupportRequestDetail)
async def get_support_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SupportRequestDetail:
    """
    Get a single support request by ID. Requires authentication.
    User must belong to the request's company or be an admin.
    """
    user = await get_current_user_required(request, db)
    stmt = select(SupportRequest).where(SupportRequest.id == request_id)
    result = await db.execute(stmt)
    support_request = result.scalar_one_or_none()
    if not support_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support request not found",
        )
    if not _can_access_support_request(user, support_request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this support request",
        )
    return _support_detail_from_model(support_request)


@router.put("/{request_id}", response_model=SupportRequestDetail)
async def update_support_request(
    request_id: UUID,
    payload: SupportRequestUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SupportRequestDetail:
    """
    Update a support request. Requires authentication.
    User must belong to the request's company or be an admin.
    Only provided fields are updated.
    """
    user = await get_current_user_required(request, db)
    stmt = select(SupportRequest).where(SupportRequest.id == request_id)
    result = await db.execute(stmt)
    support_request = result.scalar_one_or_none()
    if not support_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support request not found",
        )
    if not _can_access_support_request(user, support_request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this support request",
        )
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(support_request, key, value)
    await db.commit()
    await db.refresh(support_request)
    return _support_detail_from_model(support_request)


@router.delete("/{request_id}", response_model=SupportRequestDeleteResponse)
async def delete_support_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SupportRequestDeleteResponse:
    """
    Delete a support request once the raised concern is resolved. Requires authentication.
    User must belong to the request's company or be an admin.
    Returns a confirmation message.
    """
    user = await get_current_user_required(request, db)
    stmt = select(SupportRequest).where(SupportRequest.id == request_id)
    result = await db.execute(stmt)
    support_request = result.scalar_one_or_none()
    if not support_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support request not found",
        )
    if not _can_access_support_request(user, support_request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this support request",
        )
    await db.delete(support_request)
    await db.commit()
    return SupportRequestDeleteResponse(
        message="Support request deleted successfully. The raised concern has been marked as resolved.",
    )
