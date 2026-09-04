"""Final HTML-email assembly: the template fill + the channels-table rows."""

from datetime import datetime
from typing import Any, Dict, List

from app.core.config import settings
from app.models.email_notify_settings import EmailNotifySettings
from app.models.user import User
from app.services.email_service import email_service


class ContentMixin:
    """generate_email_content (fills the daily-summary template) + generate_channels_rows."""

    def generate_email_content(
        self,
        user: User,
        email_settings: EmailNotifySettings,
        notification_counts: Dict[str, int],
        top_channels: List[Dict[str, Any]],
        enabled_cards: str
    ) -> str:
        """
        Generate email HTML content using the daily_summary_notification.html template.

        Args:
            user: User object
            email_settings: Email notification settings
            notification_counts: Dictionary of notification counts
            top_channels: List of top channels with notification counts
            enabled_cards: HTML string of enabled notification cards (may be empty)

        Returns:
            HTML content string
        """
        try:
            template = email_service._load_template('daily_summary_notification.html')
            user_name = user.name or user.email_id.split('@')[0] if user.email_id else 'User'
            platform_name = settings.PLATFORM_NAME
            domain_url = settings.PLATFORM_URL
            domain_name = settings.PLATFORM_URL.replace('http://', '').replace('https://', '').split('/')[0]
            notification_settings_url = f"{settings.PLATFORM_URL}/settings/notifications"
            current_year = datetime.now().year
            channels_rows = self.generate_channels_rows(top_channels)
            print(f"📊 [EMAIL] Generated channels rows for {len(top_channels)} top channels")

            email_content = template.format(
                platform_name=platform_name,
                user_name=user_name,
                domain_url=domain_url,
                domain_name=domain_name,
                notification_settings_url=notification_settings_url,
                enabled_cards=enabled_cards,
                groups_rows=channels_rows,
                current_year=current_year,
                logo_html=email_service._get_embedded_logo_html(),
            )

            return email_content

        except Exception as e:
            print(f"❌ Error generating email content: {e}")
            import traceback
            print(traceback.format_exc())
            raise

    def generate_channels_rows(
        self,
        top_channels: List[Dict[str, Any]]
    ) -> str:
        """
        Generate HTML for top channels table rows with notification counts.

        Args:
            top_channels: List of channel dictionaries with notification counts

        Returns:
            HTML string for table rows
        """
        if not top_channels:
            return '<tr><td colspan="2" style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB; text-align: center;">No channels with notifications found</td></tr>'

        rows = []
        row_template = """<tr>
            <td style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB;">
                <a href="{channel_url}" class="group-name-link" style="color: #2D7DFF; text-decoration: none; font-weight: 600;">{channel_name}</a>
            </td>
            <td style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB;">
                <span class="group-count" style="color: #0D1B5A; font-weight: 700;">{notification_count}</span>
            </td>
        </tr>"""

        for channel in top_channels:
            rows.append(row_template.format(
                channel_name=channel['channel_name'],
                channel_url=channel['channel_url'],
                notification_count=channel['notification_count']
            ))

        return '\n                    '.join(rows)
