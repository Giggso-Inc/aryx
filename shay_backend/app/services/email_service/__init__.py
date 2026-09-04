"""
Email service for sending invitations and notifications.

This module provides email functionality using SMTP, specifically configured
for Gmail with app passwords for secure authentication.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 1,821-line app/services/email_service.py. It is now a package
of mixins by notification type/responsibility, combined into one
`EmailService` class below so that `from app.services.email_service import
EmailService, email_service` (used throughout the app) needs zero changes.

Each mixin module owns one notification type's send + HTML/text body-builder
methods (or, for the shared plumbing, one cross-cutting concern):
  core.py                       - SMTP config, template loading, _send_email
  diagnostics.py                - test_connection / test_email_sending (ops tools)
  branding.py                   - platform-name/user-name/logo helpers shared by all
  invitation.py / invitation_content.py
  password_reset.py / password_reset_content.py
  verification.py
  workspace_access.py
  welcome.py
  channel_notification.py / channel_notification_content.py
  error_notification.py
  support_request.py
  support_confirmation.py

All mixins share the same `self` (one EmailService instance), so method
resolution order does not matter for correctness here — no two mixins define
the same method name.
"""

from .core import CoreMixin
from .diagnostics import DiagnosticsMixin
from .branding import BrandingMixin
from .invitation import InvitationMixin
from .invitation_content import InvitationContentMixin
from .password_reset import PasswordResetMixin
from .password_reset_content import PasswordResetContentMixin
from .verification import VerificationMixin
from .workspace_access import WorkspaceAccessMixin
from .welcome import WelcomeMixin
from .channel_notification import ChannelNotificationMixin
from .channel_notification_content import ChannelNotificationContentMixin
from .error_notification import ErrorNotificationMixin
from .support_request import SupportRequestMixin
from .support_confirmation import SupportConfirmationMixin


class EmailService(
    CoreMixin,
    DiagnosticsMixin,
    BrandingMixin,
    InvitationMixin,
    InvitationContentMixin,
    PasswordResetMixin,
    PasswordResetContentMixin,
    VerificationMixin,
    WorkspaceAccessMixin,
    WelcomeMixin,
    ChannelNotificationMixin,
    ChannelNotificationContentMixin,
    ErrorNotificationMixin,
    SupportRequestMixin,
    SupportConfirmationMixin,
):
    """Service for sending emails via SMTP (see module docstring for the split map)."""


# Create a singleton instance
email_service = EmailService()

__all__ = ["EmailService", "email_service"]
