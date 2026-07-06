"""
Email verification service for handling email verification logic
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.models.company import Company
from app.core.config import settings
from app.core.auth import create_access_token, create_refresh_token
from app.core.encryption_utils import encrypt
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service

logger = logging.getLogger(__name__)


def _resolve_platform_url(platform_url: Optional[str]) -> str:
    """Normalize incoming platform URLs so emails never contain relative verify links."""
    fallback = (settings.FRONTEND_URL or settings.PLATFORM_URL or "http://localhost:3000").rstrip("/")
    candidate = (platform_url or "").strip()

    if not candidate:
        return fallback

    if candidate.startswith(("http://", "https://")):
        return candidate.rstrip("/")

    if candidate.startswith("/"):
        return fallback if candidate == "/" else f"{fallback}{candidate}".rstrip("/")

    return fallback


class EmailVerificationService:
    """Service for managing email verification tokens and processes"""
    
    def __init__(self):
        self.default_expiry_hours = int(getattr(settings, 'EMAIL_VERIFICATION_EXPIRY_HOURS', 24))
    
    async def generate_verification_token(
        self,
        email: str,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        token_type: str = "company_signup",
        db: AsyncSession = None
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
            expires_in_hours=self.default_expiry_hours
        )
        
        db.add(token)
        await db.flush()
        
        return token
    
    async def send_verification_email(
        self,
        email: str,
        token: str,
        company_name: str,
        user_name: Optional[str] = None,
        platform_url: Optional[str] = None,
        platform_name: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Send verification email to user
        
        Args:
            email: Recipient email address
            token: Verification token
            company_name: Company name
            company_name: Company name
            user_name: User's name (optional)
            platform_url: Platform base URL (optional)
            platform_name: Platform name for email templates (optional)
            
        Returns:
            bool: True if email sent successfully
        """
        platform_url = _resolve_platform_url(platform_url)
        
        # Use provided platform_name or default to config value
        platform_name_in = platform_name
        if not platform_name:
            platform_name = settings.PLATFORM_NAME
        # [DEBUG] Log so we can trace Zaptag vs generic intro and request vs default
        logger.debug("send_verification_email: platform_name incoming=%r, resolved=%r, default_config=%r", platform_name_in, platform_name, settings.PLATFORM_NAME)

        # Encrypt the token and convert to URL-safe base64 (replaces +→-, /→_, strips =)
        # Standard base64 contains / which browsers decode in URL paths when pasted,
        # splitting the token and causing "Verification Failed" on copy-paste.
        encrypted_token = encrypt(token)
        url_safe_token = encrypted_token.replace('+', '-').replace('/', '_').replace('=', '')

        # Create verification link
        verification_link = f"{platform_url}/verifyEmail/{url_safe_token}"
        # Shorten link for email (in-platform when db passed; falls back to original URL if shortening fails)
        short_verification_link = await link_shortener_service.shorten(verification_link, db=db)

        # Prepare email data (use short link in email)
        verification_data = {
            'company_name': company_name,
            'user_name': user_name or email.split('@')[0],
            'verification_link': short_verification_link,
            'expires_in_hours': self.default_expiry_hours,
            'support_email': settings.SUPPORT_EMAIL,
            'platform_name': platform_name
        }
        # [DEBUG] Confirm payload passed to email service (platform_name drives Zaptag vs generic intro)
        logger.debug("verification_data keys=%s, platform_name=%r", list(verification_data.keys()), verification_data.get('platform_name'))

        # Send email using email service
        try:
            email_sent = email_service.send_verification_email(
                to_email=email,
                verification_data=verification_data,
                platform_url=platform_url
            )
            return email_sent
        except Exception as e:
            logger.error("Error sending verification email: %s", e)
            return False
    
    async def verify_token(
        self,
        token: str,
        db: AsyncSession
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
                detail="Invalid verification token"
            )
        
        # Check if token is already used
        if verification_token.is_used:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token has already been used"
            )
        
        # Check if token is expired
        if verification_token.is_expired:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token has expired. Please request a new verification email."
            )
        
        # Get user
        user_stmt = select(User).where(User.id == verification_token.user_id)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Get company
        company_stmt = select(Company).where(Company.id == verification_token.company_id)
        company_result = await db.execute(company_stmt)
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
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
    
    async def invalidate_existing_tokens(
        self,
        email: str,
        token_type: str,
        db: AsyncSession
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
                EmailVerificationToken.is_used == False
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
    
    async def resend_verification(
        self,
        email: str,
        db: AsyncSession,
        platform_name: Optional[str] = None
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
                detail="User not found with this email"
            )
        
        # Check if user is already verified
        if user.is_verified:
            return None  # Return None to indicate user is already verified (not an error)
        
        # Get company
        if not user.company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not associated with a company"
            )
        
        company_stmt = select(Company).where(Company.id == user.company_id)
        company_result = await db.execute(company_stmt)
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
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
            db=db
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
    
    async def get_verification_status(
        self,
        email: str,
        db: AsyncSession
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
                "token_expires_at": None
            }
        
        # Find pending tokens
        token_stmt = select(EmailVerificationToken).where(
            and_(
                EmailVerificationToken.email == email,
                EmailVerificationToken.token_type == "company_signup",
                EmailVerificationToken.is_used == False,
                EmailVerificationToken.expires_at > datetime.utcnow()
            )
        ).order_by(EmailVerificationToken.created_at.desc()).limit(1)
        
        token_result = await db.execute(token_stmt)
        token = token_result.scalar_one_or_none()
        
        return {
            "is_verified": user.is_verified,
            "is_pending": not user.is_verified,
            "has_valid_token": token is not None,
            "token_expires_at": token.expires_at if token else None
        }


# Create service instance
email_verification_service = EmailVerificationService()
