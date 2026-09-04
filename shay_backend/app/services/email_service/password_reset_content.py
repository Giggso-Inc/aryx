"""HTML/text body builders for password-reset emails (used by password_reset.py)."""

from datetime import datetime


class PasswordResetContentMixin:
    """Builds the HTML/text bodies for the password-reset email flows."""

    def _create_password_reset_html(self, password_reset_data: dict, platform_url: str) -> str:
        """Create HTML version of password reset email using template file"""
        user_email = password_reset_data.get('email', '')
        user_name = password_reset_data.get('user_name', '')
        if not user_name:
            user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'User'
        reset_url = password_reset_data.get('reset_url', '')
        expires_at = password_reset_data.get('expires_at', '1 hour')
        support_email = password_reset_data.get('support_email') or self.from_email
        platform_name = self._resolve_platform_name(password_reset_data)
        current_year = datetime.now().year

        # Load template from file
        try:
            template = self._load_template('password_reset.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                user_name=user_name,
                platform_name=platform_name,
                reset_url=reset_url,
                expires_at=expires_at,
                support_email=support_email,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file password_reset.html not found")
            raise FileNotFoundError("Template file password_reset.html is required")

    def _create_password_reset_text(self, password_reset_data: dict, platform_url: str) -> str:
        """
        Create plain text version of password reset email.

        NOTE (preserved pre-existing bug): send_template_password_reset_email
        calls this with 4 positional args (password_reset_data, platform_url,
        platform_name, support_email) but this signature only accepts 2 — that
        call raises TypeError, caught by that method's own broad except, so
        the "template + db provided" success path of
        send_template_password_reset_email always returns False in practice.
        Do not "fix" this signature without also fixing the caller — it is
        characterized as-is in tests/test_email_service_characterization.py.
        """
        user_email = password_reset_data.get('email', '')
        user_name = password_reset_data.get('user_name', '')
        if not user_name:
            user_name = user_email.split('@')[0] if user_email and '@' in user_email else 'User'
        reset_url = password_reset_data.get('reset_url', '')
        expires_at = password_reset_data.get('expires_at', '1 hour')
        platform_name = self._resolve_platform_name(password_reset_data)
        support_email = password_reset_data.get('support_email') or self.from_email

        text = f"""
        Password Reset Request - {platform_name}
        =================================

        Hello {user_name},

        We received a request to reset the password for your {platform_name} workspace.
        Use the secure link below to choose a new password and get back into Aryx.

        Reset Link: {reset_url}

        IMPORTANT SECURITY INFORMATION:
        - This reset link will expire in {expires_at}
        - If you didn't request this reset, please ignore this email
        - For security, this link can only be used once

        Need help regaining access? Contact us at {support_email}.

        This email was sent from {platform_name}
        © {datetime.now().year} {platform_name}. All rights reserved.
        """

        return text

    def _get_default_password_reset_template(self) -> str:
        """Get default password reset template from file"""
        # Use the standard password_reset.html template
        try:
            return self._load_template('password_reset.html')
        except FileNotFoundError:
            raise FileNotFoundError("Template file password_reset.html is required")
