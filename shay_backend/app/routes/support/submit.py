"""
POST /submit -> submit_support_request.

Split from the original 288-line app/routes/support.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5). Unlike the other endpoints in this package, this one is
intentionally unauthenticated (user-initiated contact form) — see the
package docstring.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.support_request import SupportRequest
from app.schemas.support import SupportRequestCreate, SupportRequestResponse
from app.services.email_service import email_service

from .helpers import _generate_ticket_reference

router = APIRouter()


@router.post("/submit", response_model=SupportRequestResponse)
async def submit_support_request(
    payload: SupportRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> SupportRequestResponse:
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
