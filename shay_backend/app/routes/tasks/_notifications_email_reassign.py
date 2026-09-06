"""
send_task_reassignment_notification_email. Split out of the former
notifications_email.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to keep every resulting
file under the 150-line target; re-exported (unchanged import path) from
notifications_email.py.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.email_service import email_service
from app.models.user import User
from app.models.channel import Channel


async def send_task_reassignment_notification_email(
    recipient_user: User,
    reassigner: User,
    reassigned_user: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send task reassignment notification email to a channel member.

    Args:
        recipient_user: User who will receive the notification
        reassigner: User who reassigned the task
        reassigned_user: User who was reassigned to the task
        channel: Channel where the task was reassigned
        redirect_url: URL to redirect to view the task
        notification_settings_url: URL to notification settings page
        db: Database session

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the task reassign notification template
        template = email_service._load_template('task_reassign_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': reassigner.name or reassigner.email_id or 'Someone',
            'reassigned_user': reassigned_user.name or reassigned_user.email_id or 'User',
            'reassigned_user_email': reassigned_user.email_id or '',
            'reassigned_user_role': reassigned_user.role or 'user',
            'channel_name': channel.name or 'the channel',
            'platform_name': platform_name,
            'redirect_url': redirect_url,
            'notification_settings_url': notification_settings_url,
            'current_year': datetime.now().year,
            'logo_html': email_service._get_embedded_logo_html(),
        }

        # Process template with variables
        processed_html = template.format(**template_variables)

        # Create email message (HTML only, no plain text)
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart('alternative')
        msg['From'] = email_service.from_email
        msg['To'] = recipient_user.email_id
        msg['Subject'] = f"Task reassigned in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Task reassignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send task reassignment notification email to {recipient_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending task reassignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False
