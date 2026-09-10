"""
Email verification service for handling email verification logic.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
425-line app/services/email_verification_service.py. It is now a package of
mixins by responsibility, combined into one EmailVerificationService class
below so that `from app.services.email_verification_service import
EmailVerificationService, email_verification_service` (used throughout the
app) needs zero changes.

  send.py    - _resolve_platform_url + send_verification_email (email
               boundary: settings, encrypt, email_service, link_shortener_service)
  tokens.py  - __init__ + generate_verification_token + invalidate_existing_tokens
  verify.py  - verify_token (DB-only token verification + activation)
  resend.py  - resend_verification (reactivation + fresh token + fresh email)
  status.py  - get_verification_status (read-only status lookup)

All mixins share the same `self` (one EmailVerificationService instance), so
method resolution order does not matter for correctness here — no two
mixins define the same method name. Only TokensMixin defines __init__.
"""

from .send import SendMixin, _resolve_platform_url
from .tokens import TokensMixin
from .verify import VerifyMixin
from .resend import ResendMixin
from .status import StatusMixin

__all__ = ["EmailVerificationService", "email_verification_service", "_resolve_platform_url"]


class EmailVerificationService(TokensMixin, SendMixin, VerifyMixin, ResendMixin, StatusMixin):
    """Service for managing email verification tokens and processes."""


# Create service instance
email_verification_service = EmailVerificationService()
