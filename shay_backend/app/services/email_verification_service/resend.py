"""Resend flow: reactivation + fresh token + fresh email."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.user import User
from app.models.company import Company

logger = logging.getLogger(__name__)


class ResendMixin:
    """Resend a verification email, reactivating a soft-deleted account if needed."""

    async def resend_verification(
        self,
        email: str,
        db: AsyncSession,
        platform_name: Optional[str] = None,
    ) -> Optional[bool]:
        """
        Resend verification email

        Args:
            email: User's email address
            db: Database session

        Returns:
            Optional[bool]: True if email was sent successfully, None if user is already verified

        Raises:
            HTTPException: If user not found
        """
        # Find user by email (including inactive users for reactivation flow)
        user_stmt = select(User).where(User.email_id == email)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found with this email",
            )

        # Check if user is already verified
        if user.is_verified:
            return None  # Return None to indicate user is already verified (not an error)

        # Get company
        if not user.company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not associated with a company",
            )

        company_stmt = select(Company).where(Company.id == user.company_id)
        company_result = await db.execute(company_stmt)
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found",
            )

        # Handle reactivation: If user or company is inactive, reactivate them
        # This handles the case where company was deleted and then user tries to resend verification
        user_reactivated = False
        company_reactivated = False

        if not user.is_active:
            logger.debug("Reactivating inactive user for verification resend: %s", user.email_id)
            user.is_active = True
            user.updated_datetime = datetime.utcnow()
            user_reactivated = True

        if not company.is_active:
            logger.debug("Reactivating inactive company for verification resend: %s", company.name)
            company.is_active = True
            company.updated_at = datetime.utcnow()
            company_reactivated = True

        # Commit reactivation changes if any
        if user_reactivated or company_reactivated:
            await db.commit()
            logger.debug("Reactivated user/company for verification resend")

        # Invalidate existing tokens
        await self.invalidate_existing_tokens(email, "company_signup", db)

        # Generate new token
        new_token = await self.generate_verification_token(
            email=email,
            company_id=user.company_id,
            user_id=user.id,
            token_type="company_signup",
            db=db,
        )

        await db.commit()

        # Send verification email
        email_sent = await self.send_verification_email(
            email=email,
            token=new_token.token,
            company_name=company.name,
            user_name=user.name,
            platform_name=platform_name,
            db=db,
        )

        return email_sent
