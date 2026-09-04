"""Support-request notification (to support team): send + content builders."""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class SupportRequestMixin:
    """Send the 'new support request' notification to the support team."""

    def send_support_request_email(
        self,
        to_email: str,
        support_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """
        Send support request details to support team (support@giggso.com).

        support_data: name, email, description, subject (optional), ticket_reference, created_at.
        """
        try:
            # Logo via URL only (no MIME attachment) so inbox shows no attachment; set PLATFORM_LOGO_URL or BASE_URL for logo to load
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = f"Support Request [{support_data.get('ticket_reference', 'N/A')}] - {support_data.get('subject') or 'General'}"
            text_body = self._create_support_request_text(support_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))
            html_body = self._create_support_request_html(support_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))
            result = self._send_email(msg)
            if result:
                print(f"✅ Support request email sent to {to_email}")
            return result
        except Exception as e:
            print(f"❌ Error sending support request email to {to_email}: {e}")
            return False

    def _create_support_request_html(self, support_data: dict, platform_url: str) -> str:
        """Build HTML for support request notification (blue header, info box)."""
        import html as html_module
        name = support_data.get("name", "N/A")
        email = support_data.get("email", "N/A")
        description = (support_data.get("description") or "")[:2000]
        description_escaped = html_module.escape(description)
        subject = support_data.get("subject") or "General"
        ticket_ref = support_data.get("ticket_reference", "N/A")
        created_at = support_data.get("created_at", "")
        company_id = support_data.get("company_id") or "N/A"
        company_name = support_data.get("company_name") or "N/A"
        user_id = support_data.get("user_id") or "N/A"
        platform_name = support_data.get("platform_name", self.default_platform_name)
        current_year = datetime.now().year
        intro_message = f'A new support request has been submitted from {name}. Details are below.'
        placeholders = {
            "logo_html": self._get_embedded_logo_html(platform_name, platform_url),
            "intro_message": intro_message,
            "ticket_ref": ticket_ref,
            "subject": subject,
            "company_id": company_id,
            "company_name": company_name,
            "user_id": user_id,
            "from_name": name,
            "from_email": email,
            "created_at": created_at,
            "description": description_escaped,
            "platform_name": platform_name,
            "current_year": current_year,
        }
        try:
            template = self._load_template("support_request_notification.html")
            return self._replace_placeholders(template, placeholders)
        except FileNotFoundError:
            # Fallback inline HTML (same style as template)
            return f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"/><title>New Support Request - {platform_name}</title></head>
        <body style="font-family:Segoe UI,sans-serif;background:#F4F6FB;color:#0B1430;margin:0;padding:24px 12px">
        <div style="max-width:640px;margin:0 auto;background:#FFFFFF;border:1px solid #D9DEEB;border-radius:20px;box-shadow:0 18px 50px rgba(13,27,90,.10);overflow:hidden">
        <div style="background:#1E3A8A;background-image:linear-gradient(135deg,#0D1B5A 0%,#1E3A8A 60%,#2D7DFF 100%);color:#fff;text-align:center;padding:24px 20px">
        <h1 style="margin:0 0 8px 0;font-size:28px;font-weight:700;color:#fff">New support request</h1>
        <p style="margin:0;font-size:14px;color:#DCE8FF">Aryx support intake</p>
        </div>
        <div style="padding:36px 32px">
        <p style="font-size:18px;font-weight:600;margin-bottom:16px">Hello,</p>
        <p style="font-size:15px;line-height:1.8;margin-bottom:22px">{intro_message}</p>
        <div style="background:#F4F6FB;border:1px solid #D9DEEB;border-radius:16px;padding:20px;margin:24px 0">
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Ticket Reference:</strong> {ticket_ref}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Subject/Category:</strong> {subject}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Company ID:</strong> {company_id}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Company Name:</strong> {company_name}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">User ID:</strong> {user_id}</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">From:</strong> {name} &lt;{email}&gt;</p>
        <p style="margin:8px 0;font-size:14px"><strong style="color:#0D1B5A">Received:</strong> {created_at}</p>
        </div>
        <p style="font-size:15px;margin-bottom:8px"><strong>Description:</strong></p>
        <div style="background:#F8FAFE;border:1px solid #D9DEEB;border-radius:16px;padding:16px;white-space:pre-wrap">{description_escaped}</div>
        <p style="font-size:15px;line-height:1.7;margin-top:22px">If you have any questions or need to follow up, please use the ticket reference above.</p>
        </div>
        <div style="background:#F8FAFE;padding:24px 32px;text-align:center;border-top:1px solid #D9DEEB">
        <p style="margin:0 0 10px 0;font-size:14px">This email was sent from {platform_name}</p>
        <p style="margin:0;font-size:12px;color:#4A5A7A">© {current_year} {platform_name}. All rights reserved.</p>
        </div>
        </div></body></html>
        """

    def _create_support_request_text(self, support_data: dict, platform_url: str) -> str:
        """Build plain text body for support request notification."""
        name = support_data.get("name", "N/A")
        email = support_data.get("email", "N/A")
        description = (support_data.get("description") or "")[:2000]
        subject = support_data.get("subject") or "General"
        ticket_ref = support_data.get("ticket_reference", "N/A")
        created_at = support_data.get("created_at", "")
        company_id = support_data.get("company_id") or "N/A"
        company_name = support_data.get("company_name") or "N/A"
        user_id = support_data.get("user_id") or "N/A"
        platform_name = support_data.get("platform_name", self.default_platform_name)
        return f"""
New Support Request - {platform_name}
{self._brand_header_tagline(platform_name)}

Hello,

A new support request has been submitted from {name}. Details are below.

Ticket Reference: {ticket_ref}
Subject/Category: {subject}
Company ID: {company_id}
Company Name: {company_name}
User ID: {user_id}
From: {name} <{email}>
Received: {created_at}

Description:
-----------
{description}

If you have any questions or need to follow up, please use the ticket reference above.

This email was sent from {platform_name}
© {datetime.now().year} {platform_name}. All rights reserved.
"""
