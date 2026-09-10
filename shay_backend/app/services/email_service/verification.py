"""Email verification send + content-building (single small notification type, kept in one file)."""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class VerificationMixin:
    """Send + build the email-verification notification."""

    def send_verification_email(
        self,
        to_email: str,
        verification_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send email verification email to user

        Args:
            to_email: Recipient email address
            verification_data: Dictionary containing verification information:
                - company_name: Company name
                - user_name: User's name
                - verification_link: Verification link with token
                - expires_in_hours: Hours until token expires
                - support_email: Support email address
                - platform_name: Platform name
            platform_url: Base URL for the platform

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            platform_name = verification_data.get('platform_name', self.default_platform_name)
            subject = f"Verify Your Email - {platform_name}"
            # [DEBUG] Verification email: confirm platform_name and subject for Zaptag vs generic intro
            print(f"📧 [email_service] send_verification_email: to={to_email}, verification_data.platform_name={verification_data.get('platform_name')!r}, default_platform={self.default_platform_name!r}, subject={subject!r}")
            print(f"📧 Preparing verification email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject

            print(f"📧 Creating email content for {to_email}...")
            # Create plain text body first (should be attached before HTML)
            text_body = self._create_verification_text(verification_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_verification_html(verification_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))

            print(f"📧 Sending verification email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Verification email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send verification email to {to_email}")
            return result

        except Exception as e:
            print(f"❌ Error sending verification email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False

    def _create_verification_html(self, verification_data: dict, platform_url: str) -> str:
        """Create HTML version of verification email using template file"""
        company_name = verification_data.get('company_name', 'our platform')
        user_name = verification_data.get('user_name', 'there')
        verification_link = verification_data.get('verification_link', '')
        expires_in_hours = verification_data.get('expires_in_hours', 24)
        support_email = verification_data.get('support_email', self.from_email)
        platform_name = self._resolve_platform_name(verification_data)
        current_year = datetime.now().year
        product_intro_text = self._platform_intro_text(platform_name)

        # Load template from file
        try:
            template = self._load_template('verification.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                company_name=company_name,
                user_name=user_name,
                verification_link=verification_link,
                expires_in_hours=expires_in_hours,
                support_email=support_email,
                platform_name=platform_name,
                current_year=current_year,
                product_intro_text=product_intro_text
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file verification.html not found")
            raise FileNotFoundError("Template file verification.html is required")

    def _create_verification_text(self, verification_data: dict, platform_url: str) -> str:
        """Create plain text version of verification email"""
        company_name = verification_data.get('company_name', 'our platform')
        user_name = verification_data.get('user_name', 'there')
        verification_link = verification_data.get('verification_link', '')
        expires_in_hours = verification_data.get('expires_in_hours', 24)
        support_email = verification_data.get('support_email', self.from_email)
        platform_name = self._resolve_platform_name(verification_data)
        product_intro_text = self._platform_intro_text(platform_name)

        text = f"""
        Verify Your Email - {platform_name}
        ============================

        Hello {user_name},

        Thanks for joining {company_name} on {platform_name}.

        {product_intro_text}

        Verify your email address to activate your Aryx workspace and continue setup:

        {verification_link}

        IMPORTANT INFORMATION:
        - This verification link will expire in {expires_in_hours} hours
        - If you didn't create an account, please ignore this email
        - For security, this link can only be used once

        If you need help finishing setup, contact us at {support_email}.

        This email was sent from {platform_name}
        © 2025 {platform_name}. All rights reserved.
        """

        return text
