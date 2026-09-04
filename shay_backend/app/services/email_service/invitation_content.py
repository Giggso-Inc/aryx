"""HTML/text body builders for invitation emails (used by invitation.py)."""

from datetime import datetime
from typing import Optional


class InvitationContentMixin:
    """Builds the HTML/text bodies for the invitation email flows."""

    def _create_invitation_html(self, invitation_data: dict, platform_url: str) -> str:
        """Create HTML version of invitation email using template file"""
        company_name = invitation_data.get('company_name', 'our platform')
        registration_link = invitation_data.get('registration_link', '')
        registration_short_link = invitation_data.get('registration_short_link') or registration_link
        user_email = invitation_data.get('email', '')
        user_name = self._resolve_user_name(invitation_data, fallback="There")
        invited_by = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
        support_email = invitation_data.get('support_email') or self.from_email
        platform_name = invitation_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year

        # Load template from file
        try:
            template = self._load_template('invitation.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                company_name=company_name,
                registration_short_link=registration_short_link,
                user_name=user_name,
                invited_by=invited_by,
                support_email=support_email,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file invitation.html not found")
            raise FileNotFoundError("Template file invitation.html is required")

    def _create_invitation_text(self, invitation_data: dict, platform_url: str) -> str:
        """Create plain text version of invitation email"""
        company_name = invitation_data.get('company_name', 'our platform')
        registration_link = invitation_data.get('registration_link', '')
        registration_short_link = invitation_data.get('registration_short_link') or registration_link
        user_name = self._resolve_user_name(invitation_data, fallback="There")
        invited_by = self._normalize_name(invitation_data.get('invited_by')) or invitation_data.get('invited_by', 'Development User')
        support_email = invitation_data.get('support_email') or self.from_email
        platform_name = invitation_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year

        text = f"""
        WELCOME TO {platform_name.upper()}
        ===================

        Hello {user_name},

        {invited_by} has invited you to join {company_name} on {platform_name}.

        {self._platform_intro_text(platform_name)}

        Use this link to accept the invitation and finish setting up your workspace:
        {registration_short_link}

        Security Notice:
        - This invitation expires in 7 days
        - The link is unique to you; please do not share it

        If you need help, contact your workspace administrator or {support_email}.

        If you didn't expect this invitation, you can safely ignore this email.

        © {current_year} {platform_name}. All rights reserved.
        """

        return text

    def _get_default_invitation_template(self) -> str:
        """Get default invitation template from file"""
        # Use the standard invitation.html template
        try:
            return self._load_template('invitation.html')
        except FileNotFoundError:
            raise FileNotFoundError("Template file invitation.html is required")
