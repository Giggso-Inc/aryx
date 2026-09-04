"""
Password routes: update_current_user_password, forgot_password, reset_password.

Split out of the original monolithic app/routes/user_auth.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Kept together
since the pre-existing test coverage (tests/test_user_auth_reset.py) patches
several names in this exact area: `email_verification_service`,
`link_shortener_service`, and `_send_default_password_reset_email`.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.config import settings
from app.core.auth import get_password_hash, verify_password
from app.core.encryption_utils import decrypt
from app.services.link_shortener_service import link_shortener_service
from app.services.email_verification_service import email_verification_service

from app.models.user import User

from app.schemas.user import (
    PasswordUpdateResponse, SimplePasswordUpdateRequest,
    ForgetPasswordRequest, ForgetPasswordResponse,
    ResetPasswordRequest, ResetPasswordResponse,
)

from app.routes.user_auth._shared import _send_default_password_reset_email

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
    # Get current user from request state
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Query user in current database session
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Handle password decryption if encrypted
    old_password_to_verify = password_update.confirm_old_password
    new_password_to_use = password_update.new_password
    confirm_new_password_to_use = password_update.confirm_new_password

    if password_update.encrypted:
        try:
            # Decrypt the passwords if they are encrypted
            old_password_to_verify = decrypt(password_update.confirm_old_password)
            new_password_to_use = decrypt(password_update.new_password)
            confirm_new_password_to_use = decrypt(password_update.confirm_new_password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )
        # Validate decrypted password strength (schema skips validation when encrypted=True)
        v = new_password_to_use
        if len(v) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one digit")
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one special character")

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

    # Hash the new password using bcrypt
    new_password_hash = get_password_hash(new_password_to_use)

    # Update user's password hash
    user.password_hash = new_password_hash
    user.updated_datetime = datetime.utcnow()

    # Commit changes to database
    await db.commit()
    await db.refresh(user)

    # Return success response
    return PasswordUpdateResponse(
        message="Password updated successfully",
        updated_at=user.updated_datetime
    )


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
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from app.models.email_verification_token import EmailVerificationToken
    from app.services.email_service import EmailService
    from app.services.template_service import template_service

    # Note: Template validation is now handled in the main processing section with graceful fallback

    # Find user by email with company information
    from app.models.company import Company
    stmt = select(User, Company).outerjoin(Company, User.company_id == Company.id).where(User.email_id == forgot_password_data.email_id)
    result = await db.execute(stmt)
    row = result.first()

    # If user doesn't exist, return error
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

    # Get product name - use app_name if provided, otherwise determine from base_url
    def get_product_name_from_base_url(base_url: str) -> str:
        """Map base URL to product name"""
        base_url = base_url.lower().strip()
        if "dev-zaptag.shay-ai.com" in base_url:
            return "ZapTag"
        elif "zaptag.accsell.ai" in base_url:
            return "ZapTag"  # ZapTag production
        elif "dev-loger.shay-ai.com" in base_url:
            return "Log Analyser"
        elif "dev-fourd.shay-ai.com" in base_url:
            return "Email Support App"
        elif "dev-accell.shay-ai.com" in base_url:
            return "Accsell"
        elif "app.accsell.ai" in base_url:
            return "Accsell"  # Production Accsell
        else:
            return "Shay Suite"  # Default fallback

    # Use app_name if provided and not empty, otherwise use base_url method
    if forgot_password_data.app_name and forgot_password_data.app_name.strip():
        product_name = forgot_password_data.app_name.strip()
    else:
        product_name = get_product_name_from_base_url(forgot_password_data.base_url)

    # If user exists, send reset email
    email_sent = False
    try:
        await email_verification_service.invalidate_existing_tokens(
            user.email_id,
            "password_reset",
            db,
        )
        reset_token = EmailVerificationToken.create_token(
            email=user.email_id,
            company_id=user.company_id,
            user_id=user.id,
            token_type="password_reset",
            expires_in_hours=1,
        )
        db.add(reset_token)
        await db.flush()

        # Persist the reset token before any optional email-link shortening work.
        # The shortener uses the same DB session and can fail independently (for
        # example, when its table is unavailable), but the reset token itself must
        # still survive so the emailed link can be redeemed.
        await db.commit()

        reset_url = f"{forgot_password_data.base_url.rstrip('/')}/reset-password?token={reset_token.token}"
        # Shorten reset link for email (in-platform; falls back to original URL if shortening fails)
        short_reset_url = await link_shortener_service.shorten(reset_url, db=db)

        # Prepare template variables (use short link in email)
        template_variables = {
            'user_name': user.name or 'User',
            'company_name': product_name,  # Product name based on base_url
            'reset_link': short_reset_url,
            'expiry_hours': 1,
            'email': user.email_id,
            'token': reset_token.token
        }

        # Use template-based email if template_id is provided
        if forgot_password_data.template_id:
            try:
                # Get template content
                template_data = await template_service.get_template_content(forgot_password_data.template_id, db)
                template_content = template_data['content']

                # Process template with variables
                processed_html = template_service.process_template_content(template_content, template_variables)

                # Create email message with HTML as primary content (subject/plain use product_name)
                msg = MIMEMultipart('related')
                msg['Subject'] = f"Password Reset - {product_name} Account"
                msg['From'] = settings.SMTP_FROM
                msg['To'] = user.email_id

                # Create HTML wrapper
                html_wrapper = MIMEMultipart('alternative')

                # Add HTML content as primary
                html_part = MIMEText(processed_html, 'html', 'utf-8')
                html_part.add_header('Content-Type', 'text/html; charset=utf-8')
                html_wrapper.attach(html_part)

                # Add minimal plain text fallback (uses product_name for branding)
                text_content = f"""Password Reset Request - {product_name} Account

Hello {template_variables['user_name']},

We received a request to reset your password for your {product_name} account.

Reset Link: {short_reset_url}

This link will expire in 1 hour.

© 2025 {product_name}. All rights reserved."""

                text_part = MIMEText(text_content, 'plain', 'utf-8')
                html_wrapper.attach(text_part)

                msg.attach(html_wrapper)

                # Send email
                email_service = EmailService()
                email_sent = email_service._send_email(msg)

            except HTTPException as e:
                print(f"❌ Template not found or error: {e.detail}")
                # Fallback to default email when template is missing (use short link like other fallbacks)
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
            except Exception as e:
                print(f"❌ Error processing template: {e}")
                # Fallback to default email for other errors (use short link)
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
        else:
            # Default email (use short link)
            email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)

    except Exception as e:
        print(f"❌ Error sending forgot password email: {e}")
        email_sent = False

    # Return success response (same shape as invite: include short link for frontend parity with register flow)
    return ForgetPasswordResponse(
        message="Password reset link sent to your email address",
        email_sent=email_sent,
        reset_link=short_reset_url if email_sent else None,
    )


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
        from app.models.email_verification_token import EmailVerificationToken

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

        # Handle password decryption if encrypted
        new_password_to_use = reset_data.new_password
        confirm_new_password_to_use = reset_data.confirm_new_password

        if reset_data.encrypted:
            try:
                # Decrypt the passwords if they are encrypted
                new_password_to_use = decrypt(reset_data.new_password)
                confirm_new_password_to_use = decrypt(reset_data.confirm_new_password)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid encrypted password format"
                )

        # Validate password strength after decryption (if encrypted) or for plain text
        def validate_password_strength(password: str) -> None:
            """Validate password strength"""
            if len(password) < 8:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must be at least 8 characters long"
                )
            if not any(c.isupper() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one uppercase letter"
                )
            if not any(c.islower() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one lowercase letter"
                )
            if not any(c.isdigit() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one digit"
                )
            if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one special character"
                )

        # Validate the decrypted/plain text password
        validate_password_strength(new_password_to_use)

        # Verify new password and confirm new password match
        if new_password_to_use != confirm_new_password_to_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password and confirm new password do not match"
            )

        # Hash the new password
        new_password_hash = get_password_hash(new_password_to_use)

        # Update user's password
        user.password_hash = new_password_hash
        user.updated_datetime = datetime.utcnow()
        token_record.mark_as_used()

        # Commit changes
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
