"""
Password-setup route for SSO-only users: confirm_set_password.

Split out of the original monolithic sso_password.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import get_password_hash
from app.core.encryption_utils import decrypt

from app.models.user import User

from app.schemas.sso import SetPasswordConfirmRequest, SetPasswordConfirmResponse

router = APIRouter()


@router.post("/set-password/confirm", response_model=SetPasswordConfirmResponse)
async def confirm_set_password(
    body: SetPasswordConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> SetPasswordConfirmResponse:
    """
    Confirm and set a password for an SSO-only user using the emailed token.
    """
    from app.models.email_verification_token import EmailVerificationToken

    normalized_token = "".join(body.token.split())

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token == normalized_token
        )
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Invalid or expired token",
        })
    if not token_record.is_valid:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_002",
            "message": "This link has expired or already been used",
        })
    if token_record.token_type != "set_password":
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Invalid token type",
        })
    if str(token_record.user_id) != body.user_id:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Token does not match user",
        })

    result = await db.execute(
        select(User).where(User.id == token_record.user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail={"message": "User not found"})

    new_password_to_use = body.new_password
    confirm_password_to_use = body.confirm_password
    if body.encrypted:
        try:
            new_password_to_use = decrypt(body.new_password)
            confirm_password_to_use = decrypt(body.confirm_password)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid encrypted password format",
            )
    if new_password_to_use != confirm_password_to_use:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_003",
            "message": "Passwords do not match",
        })
    if len(new_password_to_use) < 8 or not any(c.isupper() for c in new_password_to_use) or not any(c.islower() for c in new_password_to_use) or not any(c.isdigit() for c in new_password_to_use) or not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in new_password_to_use):
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_004",
            "message": "Password must include uppercase, lowercase, digit, and special character",
        })

    user.password_hash = get_password_hash(new_password_to_use)
    token_record.mark_as_used()  # keep oauth_provider unchanged so both auth modes remain available.
    await db.commit()

    return SetPasswordConfirmResponse(
        message=(
            "Password set successfully. "
            f"You can now log in with your password or continue with "
            f"{(user.oauth_provider or 'SSO').title()}."
        ),
        success=True,
    )
