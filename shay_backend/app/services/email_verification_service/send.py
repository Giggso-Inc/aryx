"""
Platform-URL normalization + verification email dispatch.

Kept together because both the module-level helper and the mixin method
below share the same external boundary (settings, email_service,
link_shortener_service, encrypt) that outside tests patch directly on this
submodule's path.
"""

import logging
from typing import Optional

from app.core.config import settings
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


class SendMixin:
    """Send the verification email itself."""

    async def send_verification_email(
        self,
        email: str,
        token: str,
        company_name: str,
        user_name: Optional[str] = None,
        platform_url: Optional[str] = None,
        platform_name: Optional[str] = None,
        db=None,
    ) -> bool:
        """
        Send verification email to user

        Args:
            email: Recipient email address
            token: Verification token
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
        logger.debug(
            "send_verification_email: platform_name incoming=%r, resolved=%r, default_config=%r",
            platform_name_in, platform_name, settings.PLATFORM_NAME,
        )

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
            'platform_name': platform_name,
        }
        # [DEBUG] Confirm payload passed to email service (platform_name drives Zaptag vs generic intro)
        logger.debug(
            "verification_data keys=%s, platform_name=%r",
            list(verification_data.keys()), verification_data.get('platform_name'),
        )

        # Send email using email service
        try:
            email_sent = email_service.send_verification_email(
                to_email=email,
                verification_data=verification_data,
                platform_url=platform_url,
            )
            return email_sent
        except Exception as e:
            logger.error("Error sending verification email: %s", e)
            return False
