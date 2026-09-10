"""Token verification + account activation."""

from datetime import datetime
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.models.company import Company


class VerifyMixin:
    """Verify a token and activate the associated user + company."""

    async def verify_token(
        self,
        token: str,
        db: AsyncSession,
    ) -> Tuple[Company, User]:
        """
        Verify token and activate accounts

        Args:
            token: Verification token
            db: Database session

        Returns:
            Tuple[Company, User]: Activated company and user objects

        Raises:
            HTTPException: If token is invalid, expired, or already used
        """
        # Find token
        stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.token == token
        )
        result = await db.execute(stmt)
        verification_token = result.scalar_one_or_none()

        if not verification_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token",
            )

        # Check if token is already used
        if verification_token.is_used:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token has already been used",
            )

        # Check if token is expired
        if verification_token.is_expired:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token has expired. Please request a new verification email.",
            )

        # Get user
        user_stmt = select(User).where(User.id == verification_token.user_id)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Get company
        company_stmt = select(Company).where(Company.id == verification_token.company_id)
        company_result = await db.execute(company_stmt)
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found",
            )

        # Activate accounts
        user.is_verified = True
        user.is_active = True
        user.updated_datetime = datetime.utcnow()

        company.is_active = True
        company.updated_at = datetime.utcnow()

        # Mark token as used
        verification_token.mark_as_used()

        await db.commit()
        await db.refresh(user)
        await db.refresh(company)

        return company, user
