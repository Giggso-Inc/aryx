"""Read-only verification status lookup."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User


class StatusMixin:
    """Report a user's current verification/pending-token status."""

    async def get_verification_status(
        self,
        email: str,
        db: AsyncSession,
    ) -> dict:
        """
        Get verification status by email

        Args:
            email: User's email address
            db: Database session

        Returns:
            dict: Verification status information
        """
        # Find user
        user_stmt = select(User).where(User.email_id == email)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            return {
                "is_verified": False,
                "is_pending": False,
                "has_valid_token": False,
                "token_expires_at": None,
            }

        # Find pending tokens
        token_stmt = select(EmailVerificationToken).where(
            and_(
                EmailVerificationToken.email == email,
                EmailVerificationToken.token_type == "company_signup",
                EmailVerificationToken.is_used == False,
                EmailVerificationToken.expires_at > datetime.utcnow(),
            )
        ).order_by(EmailVerificationToken.created_at.desc()).limit(1)

        token_result = await db.execute(token_stmt)
        token = token_result.scalar_one_or_none()

        return {
            "is_verified": user.is_verified,
            "is_pending": not user.is_verified,
            "has_valid_token": token is not None,
            "token_expires_at": token.expires_at if token else None,
        }
