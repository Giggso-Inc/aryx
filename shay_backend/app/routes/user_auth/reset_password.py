"""
Route: reset_password.

Split out of the original password_reset.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up — the
original password_reset.py combined three endpoints in one 481-line file,
over the 150-line hard limit).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.auth import get_password_hash
from app.core.encryption_utils import decrypt

from app.models.user import User
from app.models.email_verification_token import EmailVerificationToken

from app.schemas.user import ResetPasswordRequest, ResetPasswordResponse

from app.routes.user_auth._password_validation import _validate_password_strength

router = APIRouter()


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    reset_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> ResetPasswordResponse:
    """
    Reset user password using a server-issued password reset token.

    Args:
        reset_data: ResetPasswordRequest containing user_id, email_id, and new password
        db: Database session dependency

    Returns:
        ResetPasswordResponse: Confirmation of password reset

    Raises:
        HTTPException: 400 for invalid data, 404 for user not found, 403 if account is inactive
    """
    try:
        # Normalize whitespace so copied/wrapped email links don't fail exact matching.
        reset_token = "".join(reset_data.token.split())

        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token == reset_token
            )
        )
        token_record = result.scalar_one_or_none()
        if not token_record or token_record.token_type != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token"
            )
        if not token_record.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This password reset link has expired or already been used"
            )

        result = await db.execute(
            select(User).where(
                and_(
                    User.id == token_record.user_id,
                    User.email_id == token_record.email,
                )
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or invalid reset request"
            )

        # Reject password reset for inactive users only. Active users follow same flow as before.
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive. Password reset is not available."
            )

        new_password_to_use = reset_data.new_password
        confirm_new_password_to_use = reset_data.confirm_new_password

        if reset_data.encrypted:
            try:
                new_password_to_use = decrypt(reset_data.new_password)
                confirm_new_password_to_use = decrypt(reset_data.confirm_new_password)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid encrypted password format"
                )

        _validate_password_strength(new_password_to_use)

        if new_password_to_use != confirm_new_password_to_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password and confirm new password do not match"
            )

        new_password_hash = get_password_hash(new_password_to_use)

        user.password_hash = new_password_hash
        user.updated_datetime = datetime.utcnow()
        token_record.mark_as_used()

        await db.commit()
        await db.refresh(user)

        return ResetPasswordResponse(
            message="Password has been reset successfully",
            success=True
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error resetting password: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset failed"
        )
