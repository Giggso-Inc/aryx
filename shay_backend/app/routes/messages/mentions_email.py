"""
Mention-notification email send.

Split out of the former app/routes/messages/mentions.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 / wave B2.
"""

from datetime import datetime

from app.core.config import settings
from app.models.user import User
from app.models.channel import Channel
from app.services.email_service import email_service


async def send_mention_notification_email(
    mentioned_user: User,
    comment_author: User,
    channel: Channel,
    comment_content: str,
    redirect_url: str,
    notification_settings_url: str,
    db
) -> bool:
    """
    Send mention notification email to the mentioned user.

    Args:
        mentioned_user: User who was mentioned
        comment_author: User who posted the comment
        channel: Channel where the mention occurred
        comment_content: The comment content
        redirect_url: URL to redirect to view the message/thread
        notification_settings_url: URL to notification settings page
        db: Database session (unused directly, kept for call-signature parity)

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the mention notification template
        template = email_service._load_template('mention_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': comment_author.name or comment_author.email_id or 'Someone',
            'user_email': comment_author.email_id or '',
            'user_role': comment_author.role or 'user',
            'channel_name': channel.name or 'the channel',
            'comment': comment_content,
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
        msg['To'] = mentioned_user.email_id
        msg['Subject'] = f"{comment_author.name or 'Someone'} mentioned you in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Mention notification email sent successfully to {mentioned_user.email_id}")
        else:
            print(f"❌ Failed to send mention notification email to {mentioned_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending mention notification email to {mentioned_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False
