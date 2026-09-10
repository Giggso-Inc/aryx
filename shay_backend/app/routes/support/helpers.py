"""
Shared helpers for the support route package.

Split from the original 288-line app/routes/support.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from uuid import uuid4, UUID

from app.models.support_request import SupportRequest
from app.models.user import User
from app.schemas.support import SupportRequestDetail


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
