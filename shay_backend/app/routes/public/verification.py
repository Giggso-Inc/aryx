"""Email verification endpoints: POST /verify-email and /resend-verification."""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token
from app.core.encryption_utils import decrypt_urlsafe_token
from app.core.config import settings
from app.services.email_verification_service import email_verification_service
from app.schemas.email_verification import (
    EmailVerificationRequest,
    EmailVerificationResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
)

router = APIRouter()


@router.post("/verify-email", response_model=EmailVerificationResponse)
async def verify_email(
    verification_request: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db)
) -> EmailVerificationResponse:
    """
    Verify email address using token from verification email

    This endpoint is called when user clicks the verification link in their email.
    It validates the token, activates the user and company accounts, and returns JWT tokens.
    """
    try:
        token = verification_request.token
        try:
            token = decrypt_urlsafe_token(token)
        except Exception:
            pass

        # Verify token and activate accounts
        company, user = await email_verification_service.verify_token(
            token=token,
            db=db
        )

        # Generate JWT tokens
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "company_id": str(company.id),
                "role": user.role,
                "email": user.email_id
            }
        )

        refresh_token = create_refresh_token(
            data={
                "sub": str(user.id),
                "company_id": str(company.id)
            }
        )

        # Get default workspace if exists
        default_workspace_id = None
        from app.models.workspace import Workspace
        workspace_stmt = select(Workspace).where(
            Workspace.company_id == company.id
        ).limit(1)
        workspace_result = await db.execute(workspace_stmt)
        default_workspace = workspace_result.scalar_one_or_none()
        if default_workspace:
            default_workspace_id = str(default_workspace.id)

        return EmailVerificationResponse(
            success=True,
            message="Email verified successfully! Your account has been activated.",
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=str(user.id),
            email_id=user.email_id,
            name=user.name,
            role=user.role,
            company_id=str(company.id),
            company_name=company.name,
            default_workspace_id=default_workspace_id
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify email: {str(e)}"
        )


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
