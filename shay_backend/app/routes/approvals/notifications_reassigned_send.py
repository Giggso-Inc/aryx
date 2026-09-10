"""
Email builder for the "approval reassigned" case.

Renders the reassignment template and sends it to a single recipient.
Used by notifications_reassigned_process.py.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.email_service import email_service
from app.models.channel import Channel
from app.models.user import User


async def send_approval_reassignment_notification_email(
    recipient_user: User,
    reassigner: User,
    reassigned_approver: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send approval reassignment notification email to a channel member.

    Args:
        recipient_user: User who will receive the notification
        reassigner: User who reassigned the approval
        reassigned_approver: User who was reassigned to approve
        channel: Channel where the approval was reassigned
        redirect_url: URL to redirect to view the approval
        notification_settings_url: URL to notification settings page
        db: Database session

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the approval reassign notification template
        template = email_service._load_template('approval_reassign_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': reassigner.name or reassigner.email_id or 'Someone',
            'reassigned_approval_user': reassigned_approver.name or reassigned_approver.email_id or 'User',
            'reassigned_approval_user_email': reassigned_approver.email_id or '',
            'reassigned_approval_user_role': reassigned_approver.role or 'user',
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
        msg['Subject'] = f"Approval reassigned in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Approval reassignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send approval reassignment notification email to {recipient_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending approval reassignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False
