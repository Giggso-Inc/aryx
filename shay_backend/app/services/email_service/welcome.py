"""Company-onboarding welcome email: content builders + send."""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict


class WelcomeMixin:
    """Welcome email functionality for company onboarding."""

    def _create_welcome_email_template(self, data: Dict[str, Any]) -> str:
        """Create HTML welcome email template for company onboarding using template file"""
        company_name = data.get('companyName', 'Company')
        contact_email = data.get('contactEmail', '')
        plan_name = data.get('planName', 'Plan to be selected')
        monthly_price = data.get('monthlyPrice', 0)
        app_link = data.get('appLink', '#')
        platform_name = data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year

        # Load template from file
        try:
            template = self._load_template('welcome_email.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, app_link),
                company_name=company_name,
                contact_email=contact_email,
                plan_name=plan_name,
                monthly_price=monthly_price,
                app_link=app_link,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file welcome_email.html not found")
            raise FileNotFoundError("Template file welcome_email.html is required")

    def _create_text_welcome_email(self, data: Dict[str, Any]) -> str:
        """Create plain text welcome email for company onboarding"""
        company_name = data.get('companyName', 'Company')
        contact_email = data.get('contactEmail', '')
        plan_name = data.get('planName', 'Plan to be selected')
        monthly_price = data.get('monthlyPrice', 0)
        app_link = data.get('appLink', 'N/A')

        return f"""
        Welcome to {data.get('platform_name', self.default_platform_name)}!

        Hi {company_name},

        Your {data.get('platform_name', self.default_platform_name)} workspace is ready.

        Your Account Details:
        - Company: {company_name}
        - Plan: {plan_name} - ${monthly_price}/month
        - Email: {contact_email}

        Launch Your Workspace:
        {app_link}

        Next Steps:
        - Connect a datasource or upload files
        - Review the first entities and relationships Aryx discovers
        - Start asking questions against your workspace

        If you have any questions, feel free to reach out to our support team.

        Best regards,
        The {data.get('platform_name', self.default_platform_name)} Team
        """

    def send_welcome_email(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send welcome email to new company during onboarding

        Args:
            data: Dictionary containing email data
                - companyName: Company name
                - contactEmail: Contact email address
                - planName: Subscription plan name
                - monthlyPrice: Monthly price
                - appLink: Application access link

        Returns:
            Dict with success status and message ID
        """
        try:
            # Validate required data
            if not data.get('companyName') or not data.get('contactEmail'):
                raise ValueError('Missing required data: companyName and contactEmail are required')

            # Create email content
            html_content = self._create_welcome_email_template(data)
            text_content = self._create_text_welcome_email(data)

            # Create message
            msg = MIMEMultipart('alternative')
            platform_name = data.get('platform_name', self.default_platform_name)
            msg['Subject'] = f'Welcome to {platform_name} - Your Workspace Is Ready'
            msg['From'] = self.from_email
            msg['To'] = data['contactEmail']

            # Attach both HTML and text versions
            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            # Send email using existing SMTP infrastructure
            success = self._send_email(msg)

            if success:
                return {
                    'success': True,
                    'messageId': f"welcome_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'message': 'Welcome email sent successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to send email via SMTP',
                    'message': 'Email sending failed'
                }

        except ValueError as e:
            # Configuration or data validation error
            return {
                'success': False,
                'error': str(e),
                'message': 'Email configuration error'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Failed to send welcome email: {str(e)}'
            }
