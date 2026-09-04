"""
Send-path methods for password-reset emails (body building lives in
password_reset_content.py).

Stated exception (164 lines, over the ~150 target): send_template_password_reset_email
alone is ~85 lines of one atomic template-resolution + fallback flow (mirrors
invitation.py's same-shaped stated exception); splitting it further would
separate the flow from the message it builds without isolating any
independently reusable piece.
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from fastapi import HTTPException

from app.services.template_service import template_service
from datetime import datetime

logger = logging.getLogger(__name__)


class PasswordResetMixin:
    """The two password-reset-sending entry points used by callers."""

    async def send_template_password_reset_email(
        self,
        to_email: str,
        password_reset_data: dict,
        template_id: Optional[str] = None,
        platform_url: str = "http://localhost:3000",
        db: Optional[Any] = None
    ) -> bool:
        """
        Send password reset email using template

        Args:
            to_email: Recipient email address
            password_reset_data: Dictionary containing password reset information
            template_id: Template ID to use (optional)
            platform_url: Base URL for the platform
            db: Database session (required if template_id is provided)

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "Password Reset Request"

            platform_name = self._resolve_platform_name(password_reset_data)
            support_email = password_reset_data.get('support_email') or self.from_email

            # Get template content with fallback logic
            if not template_id or not db:
                raise ValueError("Template ID and database session are required for password reset emails")

            try:
                template_data = await template_service.get_template_content(template_id, db)
                template_content = template_data['content']
            except HTTPException as e:
                if e.status_code == 404:
                    # Template not found, use default fallback
                    print(f"Template {template_id} not found, using default fallback template")
                    template_content = self._get_default_password_reset_template()
                else:
                    raise e

            # Prepare variables for template processing
            user_email = password_reset_data.get('email', '')
            user_name = password_reset_data.get('user_name', '')
            if not user_name:
                user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'there'

            template_variables = {
                'logo_html': self._get_embedded_logo_html(platform_name, platform_url),
                'user_name': user_name,
                'user_nam': user_name,  # Common typo in templates
                'email': user_email,
                'reset_url': password_reset_data.get('reset_url', ''),
                'expires_at': password_reset_data.get('expires_at', '1 hour'),
                'platform_name': platform_name,
                'platform_url': platform_url,
                'base_url': platform_url,
                'smtp_from': self.from_email,  # Add SMTP from email for templates that need it
                'support_email': support_email,
                'current_year': datetime.utcnow().year
            }

            # Process template with variables
            processed_html = template_service.process_template_content(template_content, template_variables)

            # Create plain text body first (should be attached before HTML)
            # NOTE (preserved pre-existing bug): _create_password_reset_text
            # only accepts (password_reset_data, platform_url) -- these extra
            # positional args raise TypeError, which is caught by the except
            # below, so this "template + db" path always returns False. See
            # the docstring on _create_password_reset_text in
            # password_reset_content.py, and
            # tests/test_email_service_characterization.py.
            text_body = self._create_password_reset_text(password_reset_data, platform_url, platform_name, support_email)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            msg.attach(MIMEText(processed_html, 'html'))

            # Send email
            return self._send_email(msg)

        except Exception as e:
            print(f"Error sending template password reset email: {e}")
            return False

    def send_password_reset_email(
        self,
        to_email: str,
        password_reset_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send password reset email to user using template

        Args:
            to_email: Recipient email address
            password_reset_data: Dictionary containing password reset information:
                - user_name: User's name
                - reset_url: Password reset link
                - expires_at: Expiration time (e.g., "1 hour")
                - support_email: Support email address
            platform_url: Base URL for the platform

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            print(f"📧 Preparing password reset email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"Password Reset Request - {self.default_platform_name}"

            print(f"📧 Creating email content for {to_email}...")
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_password_reset_text(password_reset_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body using template (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_password_reset_html(password_reset_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))

            print(f"📧 Sending password reset email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Password reset email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send password reset email to {to_email}")
            return result

        except Exception as e:
            print(f"❌ Error sending password reset email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False
