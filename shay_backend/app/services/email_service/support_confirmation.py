"""Support-confirmation notification (to the requester): send + content builders."""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


class SupportConfirmationMixin:
    """Send the 'we received your support request' confirmation to the user."""

    def send_support_confirmation_email(
        self,
        to_email: str,
        support_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """
        Send confirmation to user that their support request was received.
        support_data: ticket_reference, name (optional), platform_name (optional).
        """
        try:
            # Logo via URL only (no MIME attachment) so inbox shows no attachment
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = f"We received your support request - {support_data.get('ticket_reference', '')}"
            text_body = self._create_support_confirmation_text(support_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))
            html_body = self._create_support_confirmation_html(support_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))
            result = self._send_email(msg)
            if result:
                print(f"✅ Support confirmation email sent to {to_email}")
            return result
        except Exception as e:
            print(f"❌ Error sending support confirmation to {to_email}: {e}")
            return False

    def _create_support_confirmation_html(self, support_data: dict, platform_url: str) -> str:
        """Build HTML for user confirmation (blue header, info box)."""
        name = support_data.get("name", "User")
        ticket_ref = support_data.get("ticket_reference", "N/A")
        platform_name = support_data.get("platform_name", self.default_platform_name)
        support_email = getattr(settings, "SUPPORT_EMAIL", self.from_email)
        current_year = datetime.now().year
        placeholders = {
            "logo_html": self._get_embedded_logo_html(platform_name, platform_url),
            "name": name,
            "ticket_ref": ticket_ref,
            "platform_name": platform_name,
            "support_email": support_email,
            "current_year": current_year,
        }
        try:
            template = self._load_template("support_confirmation.html")
            return self._replace_placeholders(template, placeholders)
        except FileNotFoundError:
            # Fallback: inline styles so blue template renders in all email clients
            return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><meta http-equiv="Content-Type" content="text/html; charset=UTF-8" /></head>
<body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #F4F6FB; color: #0B1430; margin: 0; padding: 24px 12px;">
  <div style="max-width: 640px; margin: 0 auto; background: #FFFFFF; border: 1px solid #D9DEEB; border-radius: 20px; box-shadow: 0 18px 50px rgba(13,27,90,0.10); overflow: hidden;">
    <div style="background-color: #1E3A8A; background-image: linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%); color: #ffffff; text-align: center; padding: 24px 20px;">
      <h1 style="margin: 0 0 8px 0; font-size: 28px; font-weight: 700; color: #ffffff;">Support request received</h1>
      <p style="margin: 0; font-size: 14px; color: #DCE8FF;">We have your Aryx request</p>
    </div>
    <div style="padding: 36px 32px;">
      <p style="font-size: 18px; font-weight: 600; margin: 0 0 16px 0;">Hi {name},</p>
      <p style="font-size: 15px; line-height: 1.8; margin: 0 0 22px 0;">We have received your support request and will get back to you as soon as we can.</p>
      <div style="background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 16px; padding: 20px; margin: 24px 0;">
        <p style="margin: 8px 0; font-size: 14px;"><strong style="color: #0D1B5A;">Ticket reference:</strong> {ticket_ref}</p>
      </div>
      <p style="font-size: 15px; line-height: 1.8; margin: 0;">You can use this reference when following up. If you have any urgent questions, reply to this email or contact us at <a href="mailto:{support_email}" style="color: #2D7DFF; text-decoration: underline;">{support_email}</a>.</p>
    </div>
    <div style="background: #F8FAFE; padding: 24px 32px; text-align: center; border-top: 1px solid #D9DEEB;">
      <p style="margin: 0 0 10px 0; font-size: 14px;">This email was sent from {platform_name}</p>
      <p style="margin: 0; font-size: 12px; color: #4A5A7A;">© {current_year} {platform_name}. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
        """

    def _create_support_confirmation_text(self, support_data: dict, platform_url: str) -> str:
        """Build plain text for user confirmation email."""
        name = support_data.get("name", "User")
        ticket_ref = support_data.get("ticket_reference", "N/A")
        platform_name = support_data.get("platform_name", self.default_platform_name)
        support_email = getattr(settings, "SUPPORT_EMAIL", self.from_email)
        return f"""
Hi {name},

We have received your support request and will get back to you as soon as we can.

Ticket reference: {ticket_ref}

You can use this reference when following up. If you have any urgent questions, reply to this email or contact us at {support_email}.

— {platform_name} Support
"""
