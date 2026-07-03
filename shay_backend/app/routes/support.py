"""
Customer support routes.

User-initiated support form: submit name, email, description (optional subject).
Stores in gg_support_requests, notifies SUPPORT_EMAIL, and optionally sends confirmation to user.
GET by company_id, GET by id, UPDATE and DELETE require authentication and company access.
"""

from datetime import datetime, timezone
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.support_request import SupportRequest
from app.models.user import User
from app.schemas.support import (
    SupportRequestCreate,
    SupportRequestResponse,
    SupportRequestUpdate,
    SupportRequestDetail,
    SupportRequestListResponse,
    SupportRequestDeleteResponse,
)
from app.services.email_service import email_service

router = APIRouter()


def _support_detail_from_model(sr: SupportRequest) -> SupportRequestDetail:
    """Build SupportRequestDetail from SupportRequest model."""
    return SupportRequestDetail(
        id=sr.id,
        company_id=sr.company_id,
        company_name=sr.company_name,
        user_id=sr.user_id,
        name=sr.name,
        email=sr.email,
        description=sr.description,
        subject=sr.subject,
        ticket_reference=sr.ticket_reference,
        source=sr.source,
        created_at=sr.created_at,
    )


def _generate_ticket_reference() -> str:
    """Generate a unique ticket reference e.g. SR-ABC12DEF."""
    return "SR-" + uuid4().hex[:8].upper()


@router.post("/submit", response_model=SupportRequestResponse)
async def submit_support_request(
    payload: SupportRequestCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a user-initiated support request (contact form).

    Stores the request in the platform, sends the details to support@giggso.com
    (or SUPPORT_EMAIL from env), and sends a confirmation email to the user.
    """
    ticket_reference = _generate_ticket_reference()
    now = datetime.now(timezone.utc)

    # Create and persist support request record (company_id, company_name, user_id optional for mapping)
    support_request = SupportRequest(
        id=uuid4(),
        company_id=payload.company_id,
        company_name=(payload.company_name or "").strip() or None,
        user_id=payload.user_id,
        name=payload.name.strip(),
        email=payload.email.strip().lower(),
        description=payload.description.strip(),
        subject=(payload.subject or "General").strip() or "General",
        ticket_reference=ticket_reference,
        source="Support form",
    )
    db.add(support_request)
    await db.commit()
    await db.refresh(support_request)

    support_email = settings.SUPPORT_EMAIL or settings.SMTP_FROM
    support_data = {
        "name": support_request.name,
        "email": support_request.email,
        "description": support_request.description,
        "subject": support_request.subject,
        "ticket_reference": ticket_reference,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "platform_name": settings.PLATFORM_NAME,
        "company_id": str(support_request.company_id) if support_request.company_id else None,
        "company_name": support_request.company_name or None,
        "user_id": str(support_request.user_id) if support_request.user_id else None,
    }

    # Notify support team
    email_sent_to_support = email_service.send_support_request_email(
        to_email=support_email,
        support_data=support_data,
        platform_url=settings.PLATFORM_URL or "http://localhost:3000",
    )

    # Send confirmation to user (optional enhancement)
    confirm_data = {
        "name": support_request.name,
        "ticket_reference": ticket_reference,
        "platform_name": settings.PLATFORM_NAME,
    }
    email_service.send_support_confirmation_email(
        to_email=support_request.email,
        support_data=confirm_data,
        platform_url=settings.PLATFORM_URL or "http://localhost:3000",
    )

    if not email_sent_to_support:
        # Request is still stored; we don't fail the API, but message reflects it
        return SupportRequestResponse(
            success=True,
            message="Your support request has been recorded. We could not send the notification to the support team; they may follow up from the system.",
            ticket_reference=ticket_reference,
            created_at=support_request.created_at,
        )

    return SupportRequestResponse(
        success=True,
        message="Support request submitted successfully. You will receive a confirmation email shortly.",
        ticket_reference=ticket_reference,
        created_at=support_request.created_at,
    )


def _can_access_support_request(user: User, support_request: SupportRequest) -> bool:
    """Allow access if user is admin or support request belongs to user's company."""
    if user.is_admin:
        return True
    if support_request.company_id is None:
        return False
    return str(user.company_id) == str(support_request.company_id)


def _can_access_company_support(user: User, company_id: UUID) -> bool:
    """Allow access if user is admin or user belongs to the given company."""
    if user.is_admin:
        return True
    return user.company_id is not None and str(user.company_id) == str(company_id)


@router.get("/company/{company_id}", response_model=SupportRequestListResponse)
async def list_support_requests_by_company(
    company_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
):
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


@router.get("/{request_id}", response_model=SupportRequestDetail)
async def get_support_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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
):
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
):
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
