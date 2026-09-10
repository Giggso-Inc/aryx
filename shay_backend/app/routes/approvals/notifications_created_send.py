"""
Email builder for the "approval created" case.

Renders the created-approval template and sends it to a single
recipient. Used by notifications_created_process.py.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.email_service import email_service
from app.models.channel import Channel
from app.models.user import User


async def send_approval_notification_email(
    recipient_user: User,
    approval_creator: User,
    approver_user: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send approval notification email to a channel member.

    Args:
        recipient_user: User who will receive the notification
        approval_creator: User who created/requested the approval
        approver_user: User who needs to approve
        channel: Channel where the approval was created
        redirect_url: URL to redirect to view the approval
        notification_settings_url: URL to notification settings page
        db: Database session

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the approval notification template
        template = email_service._load_template('approval_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': approval_creator.name or approval_creator.email_id or 'Someone',
            'approval_user': approver_user.name or approver_user.email_id or 'User',
            'approval_user_email': approver_user.email_id or '',
            'approval_user_role': approver_user.role or 'user',
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
        msg['Subject'] = f"Approval requested in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Approval notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send approval notification email to {recipient_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending approval notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False
