"""Per-user daily-summary email assembly + send."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_notify_settings import EmailNotifySettings
from app.models.user import User
from app.services.email_service import email_service


class SenderMixin:
    """send_daily_summary_email: the per-user notify + SMTP-send flow."""

    async def send_daily_summary_email(
        self,
        email_settings: EmailNotifySettings,
        db: AsyncSession
    ) -> None:
        """
        Send daily summary email to a user.

        Args:
            email_settings: EmailNotifySettings record for the user
            db: Database session
        """
        try:
            # Check if notifications are enabled before sending
            # Refresh the settings from database to get the latest value
            await db.refresh(email_settings)

            if email_settings.is_notification_enabled != 1:
                print(f"⚠️ Email notifications are disabled for user {email_settings.resource_id}, skipping daily summary")
                return

            # Check if at least one notification type is enabled
            has_enabled_type = (
                email_settings.mention_enabled == 1 or
                email_settings.post_enabled == 1 or
                email_settings.reply_enabled == 1 or
                email_settings.task_enabled == 1 or
                email_settings.approval_pending_enabled == 1 or
                email_settings.meeting_enabled == 1 or
                email_settings.blocker_enabled == 1 or
                email_settings.app_enabled == 1 or
                email_settings.chat_enabled == 1 or
                email_settings.friend_enabled == 1
            )

            if not has_enabled_type:
                print(f"⚠️ No notification types enabled for user {email_settings.resource_id}, skipping daily summary")
                return

            # Get user details
            user_stmt = select(User).where(User.id == email_settings.resource_id)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if not user or not user.email_id:
                print(f"⚠️ User {email_settings.resource_id} not found or has no email")
                return

            # Collect notification counts based on enabled types
            notification_counts = await self.collect_notification_counts(
                user.id,
                email_settings,
                db
            )

            # Generate enabled cards HTML (only for enabled notification types with count > 0)
            enabled_cards = self.generate_enabled_cards(email_settings, notification_counts)

            # Get top 5 channels with notification counts
            top_channels = await self.get_top_channels(user.id, email_settings, db)

            # Only send email if there are either enabled cards (with count > 0) OR top channels
            if not enabled_cards and not top_channels:
                print(f"⚠️ No enabled notification types with data and no channels with notifications for user {user.email_id}, skipping daily summary")
                return

            # Generate email content (will handle case where enabled_cards is empty but channels exist)
            email_content = self.generate_email_content(
                user,
                email_settings,
                notification_counts,
                top_channels,
                enabled_cards
            )

            # Check if email content was generated
            if email_content is None or not email_content.strip():
                print(f"⚠️ No email content generated for user {user.email_id}, skipping send")
                return

            # Send email
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart('alternative')
            msg['From'] = email_service.from_email
            msg['To'] = user.email_id
            msg['Subject'] = f"Daily Summary - {settings.PLATFORM_NAME}"

            # Attach HTML content
            msg.attach(MIMEText(email_content, 'html'))

            # Send email
            result = email_service._send_email(msg)

            if result:
                # Update last_email_notify_time
                email_settings.last_email_notify_time = datetime.now(timezone.utc)
                await db.commit()
                print(f"✅ Daily summary email sent to {user.email_id}")
            else:
                print(f"❌ Failed to send daily summary email to {user.email_id}")

        except Exception as e:
            print(f"❌ Error sending daily summary email: {e}")
            import traceback
            print(traceback.format_exc())
            raise
