"""
Route: forgot_password.

Split out of the original password_reset.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up — the
original password_reset.py combined three endpoints in one 481-line file,
over the 150-line hard limit). The email-construction/sending logic lives in
`_forgot_password_helpers.py`.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db

from app.models.user import User
from app.models.company import Company

from app.schemas.user import ForgetPasswordRequest, ForgetPasswordResponse

from app.routes.user_auth._forgot_password_helpers import (
    _product_name_from_base_url, _generate_and_send_reset_email,
)

router = APIRouter()


@router.post("/forgot-password", response_model=ForgetPasswordResponse)
async def forgot_password(
    forgot_password_data: ForgetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> ForgetPasswordResponse:
    """
    Send password reset link to user's email.

    This endpoint generates an encrypted reset link containing user information
    and timestamp, then sends it via email using template system. The link expires after 1 hour.

    Args:
        forgot_password_data: ForgetPasswordRequest containing email address, base_url,
                            optional template_id, and optional app_name for product name
        db: Database session dependency

    Returns:
        ForgetPasswordResponse: Confirmation that email was sent

    Raises:
        HTTPException: 404 if email not found, 403 if account is inactive
    """
    stmt = select(User, Company).outerjoin(Company, User.company_id == Company.id).where(
        User.email_id == forgot_password_data.email_id
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email doesn't exist"
        )

    user, company = row

    # Do not send reset email to inactive users; return error in response instead.
    # Active users continue with the same flow as before (reset URL + email).
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Password reset is not available."
        )

    if forgot_password_data.app_name and forgot_password_data.app_name.strip():
        product_name = forgot_password_data.app_name.strip()
    else:
        product_name = _product_name_from_base_url(forgot_password_data.base_url)

    email_sent, short_reset_url = await _generate_and_send_reset_email(
        user, forgot_password_data.base_url, product_name, forgot_password_data.template_id, db
    )

    # Return success response (same shape as invite: include short link for frontend parity with register flow)
    return ForgetPasswordResponse(
        message="Password reset link sent to your email address",
        email_sent=email_sent,
        reset_link=short_reset_url if email_sent else None,
    )
