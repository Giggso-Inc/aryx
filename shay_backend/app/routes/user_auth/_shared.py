"""
Cross-cutting helpers shared across the user_auth route submodules.

Split out of the original monolithic app/routes/user_auth.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Both helpers here
are used by more than one submodule:

- `_format_user_name_from_email` is used by invitations.py.
- `_send_default_password_reset_email` is used by password_reset.py's
  `forgot_password` endpoint (kept here so both existing test files that
  patch it can be pointed at one stable path).
"""

import re


def _format_user_name_from_email(email: str, default: str = "User") -> str:
    """
    Convert the local part of an email address into a display name with each word capitalized.

    Args:
        email: The email address to parse.
        default: Fallback value when the email is missing or cannot be parsed.

    Returns:
        A title-cased name derived from the email address, or the provided default.
    """
    if not email or '@' not in email:
        return default

    local_part = email.split('@')[0]
    # Replace common separators with spaces and collapse multiple spaces
    cleaned = re.sub(r"[._\-]+", " ", local_part)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned.title() if cleaned else default


async def _send_default_password_reset_email(user, reset_url, product_name="Shay Suite") -> bool:
    """Send default password reset email (fallback when no template is used)"""
    try:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from app.services.email_service import EmailService
        from app.core.config import settings

        # Create email content
        subject = f"Password Reset - {product_name} Account"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset - {product_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background-color: #ffffff; padding: 30px; border: 1px solid #e9ecef; }}
                .footer {{ background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px; font-size: 14px; color: #6c757d; }}
                .reset-button {{ display: inline-block; background-color: #007bff; color: #ffffff !important; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; font-weight: bold; }}
                .warning {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .link-fallback {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; word-break: break-all; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 Password Reset Request</h1>
                </div>
                <div class="content">
                    <h2>Hello {user.name or 'User'},</h2>

                    <p>We received a request to reset your password for your {product_name} account. Click the button below to reset your password.</p>

                    <div style="text-align: center; margin: 24px 0;">
                        <a href="{reset_url}" class="reset-button" style="display: inline-block; background-color: #007bff; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; font-family: Arial, sans-serif;">Reset My Password</a>
                    </div>

                    <div class="warning">
                        <strong>⚠️ Important Security Information:</strong>
                        <ul>
                            <li>This link will expire in <strong>1 hour</strong></li>
                            <li>If you didn't request this reset, please ignore this email</li>
                            <li>For security, this link can only be used once</li>
                        </ul>
                    </div>

                    <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                    <div class="link-fallback">{reset_url}</div>

                    <p>If you have any questions or need assistance, please contact your system administrator.</p>
                </div>
                <div class="footer">
                    <p>This email was sent from {settings.SMTP_FROM}</p>
                    <p>© 2025 {product_name}. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Password Reset Request - {product_name} Account

        Hello {user.name or 'User'},

        We received a request to reset your password for your {product_name} account. Click the link below to reset your password.

        Reset Link: {reset_url}

        IMPORTANT SECURITY INFORMATION:
        - This link will expire in 1 hour
        - If you didn't request this reset, please ignore this email
        - For security, this link can only be used once

        If you have any questions or need assistance, please contact your system administrator.

        This email was sent from {settings.SMTP_FROM}
        © 2025 {product_name}. All rights reserved.
        """

        # Create email message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = settings.SMTP_FROM
        msg['To'] = user.email_id

        # Add text and HTML parts
        text_part = MIMEText(text_content, 'plain')
        html_part = MIMEText(html_content, 'html')

        msg.attach(text_part)
        msg.attach(html_part)

        # Send email
        email_service = EmailService()
        return email_service._send_email(msg)

    except Exception as e:
        print(f"❌ Error sending default password reset email: {e}")
        return False
