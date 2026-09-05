"""
Password-setup route for SSO-only users: request_set_password.

Split out of the original monolithic sso_password.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.services.email_service import email_service

from app.models.user import User

from app.schemas.sso import SetPasswordRequestBody, SetPasswordRequestResponse

router = APIRouter()


@router.post("/set-password/request", response_model=SetPasswordRequestResponse)
async def request_set_password(
    body: SetPasswordRequestBody,
    db: AsyncSession = Depends(get_db),
) -> SetPasswordRequestResponse:
    """
    For SSO-only users who want to add a password.
    Always returns the same response to avoid email enumeration.
    """
    from app.models.email_verification_token import EmailVerificationToken

    result = await db.execute(
        select(User).where(User.email_id == body.email_id)
    )
    user = result.scalar_one_or_none()

    # Never reveal whether the email exists or whether the account is SSO-only.
    if user and user.password_hash is None:
        token = EmailVerificationToken.create_token(
            email=user.email_id,
            company_id=str(user.company_id),
            user_id=str(user.id),
            token_type="set_password",
            expires_in_hours=24,
        )
        db.add(token)
        await db.commit()
        set_password_link = (
            f"{settings.FRONTEND_URL}/set-password"
            f"?token={token.token}&user_id={user.id}"
        )
        email_service.send_password_reset_email(
            user.email_id,
            {
                "email": user.email_id,
                "user_name": user.name or "User",
                "reset_url": set_password_link,
                "expires_at": "24 hours",
                "platform_name": settings.PLATFORM_NAME,
            },
            settings.FRONTEND_URL,
        )  # reuse the existing password-reset email template flow.

    return SetPasswordRequestResponse(
        message="If this email exists, a password setup link has been sent."
    )
