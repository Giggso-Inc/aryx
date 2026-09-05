"""
Route: update_current_user_password.

Split out of the original password_reset.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up — the
original password_reset.py combined three endpoints in one 481-line file,
over the 150-line hard limit).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import get_password_hash, verify_password
from app.core.encryption_utils import decrypt

from app.models.user import User

from app.schemas.user import PasswordUpdateResponse, SimplePasswordUpdateRequest

from app.routes.user_auth._password_validation import _validate_password_strength

router = APIRouter()


@router.put("/password", response_model=PasswordUpdateResponse)
async def update_current_user_password(
    password_update: SimplePasswordUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> PasswordUpdateResponse:
    """
    Update current user's password with a three-field validation process.

    This endpoint allows authenticated users to update their password by:
    1. Confirming their current password
    2. Entering a new password
    3. Confirming the new password

    Args:
        password_update: SimplePasswordUpdateRequest containing confirm old password, new password, and confirm new password
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        PasswordUpdateResponse: Success message and update timestamp

    Raises:
        HTTPException: 401 if not authenticated, 400 if validation fails, 404 if user not found

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 19/08/2025
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    old_password_to_verify = password_update.confirm_old_password
    new_password_to_use = password_update.new_password
    confirm_new_password_to_use = password_update.confirm_new_password

    if password_update.encrypted:
        try:
            old_password_to_verify = decrypt(password_update.confirm_old_password)
            new_password_to_use = decrypt(password_update.new_password)
            confirm_new_password_to_use = decrypt(password_update.confirm_new_password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )
        # Validate decrypted password strength (schema skips validation when encrypted=True)
        _validate_password_strength(new_password_to_use)

    # STEP 1: Verify old password matches stored password
    if not verify_password(old_password_to_verify, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # STEP 2: Verify new password and confirm new password match
    if new_password_to_use != confirm_new_password_to_use:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm new password do not match"
        )

    # Check if new password is different from old password
    if old_password_to_verify == new_password_to_use:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )

    new_password_hash = get_password_hash(new_password_to_use)

    user.password_hash = new_password_hash
    user.updated_datetime = datetime.utcnow()

    await db.commit()
    await db.refresh(user)

    return PasswordUpdateResponse(
        message="Password updated successfully",
        updated_at=user.updated_datetime
    )
