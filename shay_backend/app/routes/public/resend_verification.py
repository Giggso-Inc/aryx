"""POST /resend-verification.

Split from the original verification.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.email_verification import ResendVerificationRequest, ResendVerificationResponse
from app.services.email_verification_service import email_verification_service

router = APIRouter()


@router.post("/resend-verification", response_model=ResendVerificationResponse)
async def resend_verification(
    resend_request: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db)
) -> ResendVerificationResponse:
    """
    Resend verification email to user

    This endpoint allows users to request a new verification email if:
    - They didn't receive the original email
    - The verification link expired
    - They need a new verification link
    """
    try:
        # Use platform_name from request if provided, otherwise use config default
        platform_name = resend_request.platform_name or settings.PLATFORM_NAME

        email_sent = await email_verification_service.resend_verification(
            email=resend_request.email,
            db=db,
            platform_name=platform_name
        )

        # Handle case where user is already verified (returns None)
        if email_sent is None:
            return ResendVerificationResponse(
                success=True,
                message="Your email is already verified. No verification email needed.",
                email_sent=False  # No email sent because user is already verified
            )

        if email_sent:
            return ResendVerificationResponse(
                success=True,
                message="Verification email has been resent successfully. Please check your inbox.",
                email_sent=True
            )
        else:
            return ResendVerificationResponse(
                success=False,
                message="Failed to send verification email. Please try again later or contact support.",
                email_sent=False
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend verification email: {str(e)}"
        )
