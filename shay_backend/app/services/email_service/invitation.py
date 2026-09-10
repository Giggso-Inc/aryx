"""
Send-path methods for invitation emails (body building lives in
invitation_content.py).

Stated exception (189 lines, over the ~150 target): send_template_invitation_email
alone is ~90 lines of one atomic template-resolution + fallback flow; splitting
it further would separate the template/fallback logic from the message it
builds without isolating any independently reusable piece.
"""

import logging
from typing import Any, List, Optional

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import HTTPException

from app.services.template_service import template_service
from datetime import datetime

logger = logging.getLogger(__name__)


class InvitationMixin:
    """The three invitation-sending entry points used by callers."""

    async def send_template_invitation_email(
        self,
        to_email: str,
        invitation_data: dict,
        template_id: Optional[str] = None,
        platform_url: str = "http://localhost:3000",
        db: Optional[Any] = None
    ) -> bool:
        """
        Send invitation email using template

        Args:
            to_email: Recipient email address
            invitation_data: Dictionary containing invitation information
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
            msg['Subject'] = "Invitation to join Aryx"

            # Get template content with fallback logic
            if template_id and db:
                try:
                    template_data = await template_service.get_template_content(template_id, db)
                    template_content = template_data['content']
                except HTTPException as e:
                    if e.status_code == 404:
                        logger.warning("Template %s not found, falling back to default", template_id)
                        template_content = self._get_default_invitation_template()
                    else:
                        raise e
            else:
                template_content = self._get_default_invitation_template()

            # Prepare variables for template processing
            user_email = invitation_data.get('email', '')
            user_name = self._resolve_user_name(invitation_data, fallback="There")
            invited_by_display = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
            company_name = invitation_data.get('company_name', self.default_platform_name)
            platform_name = self._resolve_platform_name(invitation_data)
            support_email = invitation_data.get('support_email') or self.from_email

            template_variables = {
                'company_name': company_name,
                'logo_html': self._get_embedded_logo_html(platform_name, platform_url),
                'user_name': user_name,
                'user_nam': user_name,  # Support common placeholder typo
                'invited_by': invited_by_display,
                'role': invitation_data.get('role', 'user'),
                'registration_link': invitation_data.get('registration_link', ''),
                'registration_short_link': invitation_data.get('registration_short_link') or invitation_data.get('registration_link', ''),
                'invite_id': invitation_data.get('invite_id', ''),
                'expires_at': invitation_data.get('expires_at', ''),
                'email': user_email,
                'smtp_from': self.from_email,  # Add SMTP from email for templates that need it
                'platform_name': platform_name,
                'support_email': support_email,
                'current_year': datetime.utcnow().year
            }

            # Process template with variables
            try:
                processed_html = template_service.process_template_content(template_content, template_variables)
            except ValueError as e:
                logger.warning("Template processing error, falling back to default HTML: %s", e)
                processed_html = self._create_invitation_html(invitation_data, platform_url)

            # Create plain text body first (should be attached before HTML)
            text_body = self._create_invitation_text(invitation_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            msg.attach(MIMEText(processed_html, 'html'))

            # Send email
            return self._send_email(msg)

        except Exception as e:
            logger.error("Error sending template invitation email to %s: %s", to_email, e, exc_info=True)
            return False

    def send_invitation_email(
        self,
        to_email: str,
        invitation_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send invitation email to user

        Args:
            to_email: Recipient email address
            invitation_data: Dictionary containing invitation information
            platform_url: Base URL for the platform

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = "Invitation to join Aryx"

            # Create plain text body first (should be attached before HTML)
            text_body = self._create_invitation_text(invitation_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_invitation_html(invitation_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))

            # Send email
            return self._send_email(msg)

        except Exception as e:
            logger.error("Error sending invitation email to %s: %s", to_email, e, exc_info=True)
            return False

    def send_bulk_invitation_emails(
        self,
        invitations: List[dict],
        platform_url: str = "http://localhost:3000"
    ) -> dict:
        """
        Send bulk invitation emails

        Args:
            invitations: List of invitation dictionaries
            platform_url: Base URL for the platform

        Returns:
            dict: Results of bulk email sending
        """
        results = {
            'successful': [],
            'failed': []
        }

        for invitation in invitations:
            try:
                success = self.send_invitation_email(
                    invitation['email_id'],
                    invitation,
                    platform_url
                )

                if success:
                    results['successful'].append(invitation['email_id'])
                else:
                    results['failed'].append({
                        'email': invitation['email_id'],
                        'reason': 'Email sending failed'
                    })

            except Exception as e:
                results['failed'].append({
                    'email': invitation['email_id'],
                    'reason': str(e)
                })

        return results
