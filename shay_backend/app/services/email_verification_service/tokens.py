"""Token lifecycle: creation and bulk invalidation."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.email_verification_token import EmailVerificationToken
from app.core.config import settings


class TokensMixin:
    """Create new verification tokens and invalidate stale ones.

    Owns __init__ for the whole EmailVerificationService: no other mixin in
    this package defines one, so this is the only constructor in the MRO.
    """

    def __init__(self):
        self.default_expiry_hours = int(getattr(settings, 'EMAIL_VERIFICATION_EXPIRY_HOURS', 24))

    async def generate_verification_token(
        self,
        email: str,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        token_type: str = "company_signup",
        db: AsyncSession = None,
    ) -> EmailVerificationToken:
        """
        Generate a new verification token

        Args:
            email: User's email address
            company_id: Company UUID
            user_id: User UUID
            token_type: Type of token (default: "company_signup")
            db: Database session

        Returns:
            EmailVerificationToken: Created token object
        """
        # Invalidate existing tokens for this email/type
        await self.invalidate_existing_tokens(email, token_type, db)

        # Create new token
        token = EmailVerificationToken.create_token(
            email=email,
            company_id=company_id,
            user_id=user_id,
            token_type=token_type,
            expires_in_hours=self.default_expiry_hours,
        )

        db.add(token)
        await db.flush()

        return token

    async def invalidate_existing_tokens(
        self,
        email: str,
        token_type: str,
        db: AsyncSession,
    ) -> bool:
        """
        Invalidate all existing pending tokens for email/type

        Args:
            email: User's email address
            token_type: Type of token
            db: Database session

        Returns:
            bool: True if tokens were invalidated
        """
        # Find all unused tokens for this email/type
        stmt = select(EmailVerificationToken).where(
            and_(
                EmailVerificationToken.email == email,
                EmailVerificationToken.token_type == token_type,
                EmailVerificationToken.is_used == False,
            )
        )
        result = await db.execute(stmt)
        tokens = result.scalars().all()

        # Mark all as used
        for token in tokens:
            token.mark_as_used()

        if tokens:
            await db.flush()

        return True
