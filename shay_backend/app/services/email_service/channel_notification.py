"""Send-path + branch-selection logic for channel-member notification emails."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List


class ChannelNotificationMixin:
    """Send the channel-member-added notification (admin or added-user branch)."""

    def send_channel_member_notification(
        self,
        to_emails: List[str],
        notification_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send channel member notification. Content depends on notification_data.send_to_added_user:
        - send_to_added_user True (Accsell/Zaptag added-user email): "You have been added...", View Channel button.
        - Otherwise (original admin email): "A new user has been added...", no View Channel button.

        Args:
            to_emails: Admin emails for admin notification; or [added_user_email] when send_to_added_user=True.
            notification_data: channel_name, user_name, user_email, user_role, added_by, platform_name; channel_id and send_to_added_user=True for added-user email.
            platform_url: Base URL for the platform (used for View Channel link when send_to_added_user=True).
        """
        if not to_emails:
            return True

        # [DEBUG] Log raw payload received so we can trace root cause
        raw_send_flag = notification_data.get('send_to_added_user')
        print(f"📧 [email_service] send_channel_member_notification received: keys={list(notification_data.keys())}, send_to_added_user raw={raw_send_flag!r} (type={type(raw_send_flag).__name__})")
        platform_name = notification_data.get('platform_name', self.default_platform_name)
        channel_name = notification_data.get('channel_name', 'the channel')
        user_name = notification_data.get('user_name', 'A user')
        user_email = notification_data.get('user_email', '')
        user_role = notification_data.get('user_role', 'member')
        added_by = notification_data.get('added_by', 'an administrator')

        # Compute once so subject and body never diverge (single source of truth for added-user vs admin branch)
        send_to_added_user = self._is_send_to_added_user(notification_data)
        # Log platform_name and branch for debugging (confirm Accsell/Zaptag and added_user vs admin)
        print(f"📧 Channel member email: platform_name={platform_name!r}, send_to_added_user={send_to_added_user} -> {'added_user (You have been added + View Channel)' if send_to_added_user else 'admin (New user added)'}")
        subject = (
            f"You have been added to channel - {channel_name}"
            if send_to_added_user
            else f"New User Added to Channel - {channel_name}"
        )
        # [DEBUG] One-line summary before sending so we can confirm branch and recipients
        channel_id = notification_data.get('channel_id', '')
        print(f"📧 [email_service] send_channel_member_notification: subject={subject!r}, send_to_added_user={send_to_added_user}, to_emails_count={len(to_emails)}, channel_id={channel_id!r}, platform_name={platform_name!r}")
        results = []
        for to_email in to_emails:
            try:
                print(f"📧 Preparing channel member notification email for {to_email}...")
                # Create message with 'alternative' subtype so email clients show only one version
                msg = MIMEMultipart('alternative')
                msg['From'] = self.from_email
                msg['To'] = to_email
                msg['Subject'] = subject

                # Pass send_to_added_user explicitly so body uses same branch as subject (no re-read from dict)
                text_body = self._create_channel_member_notification_text(
                    notification_data, platform_url, send_to_added_user=send_to_added_user
                )
                msg.attach(MIMEText(text_body, 'plain'))

                # Pass send_to_added_user explicitly so body uses same branch as subject
                html_body = self._create_channel_member_notification_html(
                    notification_data, platform_url, send_to_added_user=send_to_added_user
                )
                msg.attach(MIMEText(html_body, 'html'))

                # Send email
                result = self._send_email(msg)
                if result:
                    print(f"✅ Channel member notification email sent successfully to {to_email}")
                else:
                    print(f"❌ Failed to send channel member notification email to {to_email}")
                results.append(result)
            except Exception as e:
                print(f"❌ Error sending channel member notification email to {to_email}: {e}")
                results.append(False)

        return all(results)

    def _is_send_to_added_user(self, notification_data: dict) -> bool:
        """True when email is for the added user (Accsell/Zaptag). Accepts bool True, 1, and strings 'true'/'1' so subject and body stay in sync after JSON/serialization."""
        v = notification_data.get('send_to_added_user')
        # Treat explicit truthy values so serialization (e.g. JSON true -> 1 or "true") doesn't break
        if v is True:
            return True
        if v == 1 or (isinstance(v, str) and v.strip().lower() in ('true', '1')):
            return True
        # [DEBUG] Log when we fall back to False so we can spot missing or wrong values
        if v is not None and v is not False:
            print(f"📧 [email_service] _is_send_to_added_user: raw value={v!r}, type={type(v).__name__} -> False (expected True for added-user email)")
        return False
