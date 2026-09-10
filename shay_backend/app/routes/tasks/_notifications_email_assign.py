"""
send_task_assignment_notification_email. Split out of the former
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


async def send_task_assignment_notification_email(
    recipient_user: User,
    task_creator: User,
    assigned_user: User,
    channel: Channel,
    task_title: str,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send task assignment notification email to a channel member.

    Args:
        recipient_user: User who will receive the notification
        task_creator: User who created/assigned the task
        assigned_user: User who was assigned the task
        channel: Channel where the task was created
        task_title: Title of the task
        redirect_url: URL to redirect to view the task
        notification_settings_url: URL to notification settings page
        db: Database session

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the task notification template
        template = email_service._load_template('task_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': task_creator.name or task_creator.email_id or 'Someone',
            'assigned_user': assigned_user.name or assigned_user.email_id or 'User',
            'assigned_user_email': assigned_user.email_id or '',
            'assigned_user_role': assigned_user.role or 'user',
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
        msg['Subject'] = f"Task assigned in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Task assignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send task assignment notification email to {recipient_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending task assignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False
