"""Workspace-access notification: send + HTML/text content (single notification type)."""

import asyncio
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class WorkspaceAccessMixin:
    """Notify an existing user that they were added to a workspace."""

    async def send_workspace_access_email(
        self,
        to_email: str,
        workspace_access_data: dict,
        platform_url: str = "http://localhost:3000",
    ) -> bool:
        """Notify an existing user that they were added to a workspace."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = "You have been added to an Aryx workspace"

            text_body = self._create_workspace_access_text(workspace_access_data, platform_url)
            msg.attach(MIMEText(text_body, "plain"))

            html_body = self._create_workspace_access_html(workspace_access_data, platform_url)
            msg.attach(MIMEText(html_body, "html"))

            return await asyncio.to_thread(self._send_email, msg)
        except Exception:
            logger.exception("Error sending workspace access email")
            return False

    def _create_workspace_access_html(self, workspace_access_data: dict, platform_url: str) -> str:
        """Create HTML for the workspace access notification email."""
        workspace_name = workspace_access_data.get("workspace_name", "your workspace")
        user_name = workspace_access_data.get("user_name") or "there"
        role = workspace_access_data.get("role", "member")
        added_by = workspace_access_data.get("added_by", "A workspace administrator")
        platform_name = workspace_access_data.get("platform_name", self.default_platform_name)
        support_email = workspace_access_data.get("support_email") or self.from_email
        current_year = datetime.now().year

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>You have been added to {workspace_name}</title>
</head>
<body style="margin: 0; padding: 24px 12px; background-color: #F4F6FB; color: #0B1430; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, Helvetica, sans-serif;">
  <div style="max-width: 640px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #D9DEEB; border-radius: 20px; overflow: hidden; box-shadow: 0 18px 50px rgba(13, 27, 90, 0.10);">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #1E3A8A; background-image: linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%); color: #FFFFFF;">
      <tr>
        <td style="padding: 28px 24px 12px 24px; text-align: center;">{self._get_embedded_logo_html(platform_name, platform_url)}</td>
      </tr>
      <tr>
        <td style="padding: 0 24px 28px 24px; text-align: center;">
          <h1 style="margin: 0; font-size: 28px; line-height: 1.2; font-weight: 700; color: #FFFFFF;">You have been added to a workspace</h1>
          <p style="margin: 10px 0 0 0; font-size: 14px; line-height: 1.5; color: #DCE8FF;">{self._brand_header_tagline(platform_name)}</p>
        </td>
      </tr>
    </table>

    <div style="padding: 36px 32px;">
      <p style="margin: 0 0 16px 0; font-size: 20px; line-height: 1.4; font-weight: 600; color: #0B1430;">Hello {user_name},</p>

      <p style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.8; color: #0B1430;">
        <strong>{added_by}</strong> added you to the <strong>{workspace_name}</strong> workspace in <strong>{platform_name}</strong>.
      </p>

      <div style="margin: 0 0 24px 0; padding: 20px 22px; background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 16px;">
        <p style="margin: 0 0 8px 0; font-size: 14px; line-height: 1.7; color: #0B1430;"><strong style="color: #0D1B5A;">Workspace:</strong> {workspace_name}</p>
        <p style="margin: 0; font-size: 14px; line-height: 1.7; color: #0B1430;"><strong style="color: #0D1B5A;">Role:</strong> {role.capitalize()}</p>
      </div>

      <p style="margin: 0 0 22px 0; font-size: 15px; line-height: 1.8; color: #0B1430;">
        Sign in to open your workspace and start collaborating with your team.
      </p>

      <div style="text-align: center; margin: 0 0 20px 0;">
        <a href="{platform_url}" style="display: inline-block; padding: 14px 30px; border-radius: 999px; background-color: #2D7DFF; color: #FFFFFF; text-decoration: none; font-size: 15px; line-height: 1.4; font-weight: 700;">Open Workspace</a>
      </div>

      <div style="margin: 0 0 24px 0; padding: 16px 18px; background-color: #F8FAFE; border-radius: 14px; border: 1px dashed #BED1F8; font-size: 13px; line-height: 1.7; color: #0B1430; word-break: break-all;">
        If the button does not work, use this link:
        <br />
        <a href="{platform_url}" style="color: #2D7DFF; text-decoration: underline;">{platform_url}</a>
      </div>

      <p style="margin: 0; font-size: 14px; line-height: 1.7; color: #0B1430;">
        Need help getting started? Contact your workspace administrator or <a href="mailto:{support_email}" style="color: #2D7DFF; text-decoration: underline;">{support_email}</a>.
      </p>
    </div>

    <div style="padding: 24px 32px; background-color: #F8FAFE; border-top: 1px solid #D9DEEB; text-align: center;">
      <p style="margin: 0 0 8px 0; font-size: 13px; line-height: 1.6; color: #4A5A7A;">This email was sent from {platform_name}.</p>
      <p style="margin: 0; font-size: 13px; line-height: 1.6; font-weight: 600; color: #0D1B5A;">© {current_year} {platform_name}. All rights reserved.</p>
    </div>
  </div>
</body>
</html>
        """

    def _create_workspace_access_text(self, workspace_access_data: dict, platform_url: str) -> str:
        """Create plain text for the workspace access notification email."""
        workspace_name = workspace_access_data.get("workspace_name", "your workspace")
        user_name = workspace_access_data.get("user_name") or "there"
        role = workspace_access_data.get("role", "member")
        added_by = workspace_access_data.get("added_by", "A workspace administrator")
        platform_name = workspace_access_data.get("platform_name", self.default_platform_name)
        support_email = workspace_access_data.get("support_email") or self.from_email
        current_year = datetime.now().year

        return f"""
        YOU HAVE BEEN ADDED TO {platform_name.upper()}
        ===================

        Hello {user_name},

        {added_by} added you to the {workspace_name} workspace in {platform_name}.

        Workspace: {workspace_name}
        Role: {role}

        Sign in to open your workspace:
        {platform_url}

        If you need help, contact your workspace administrator or {support_email}.

        This email was sent from {platform_name}
        © {current_year} {platform_name}. All rights reserved.
        """
