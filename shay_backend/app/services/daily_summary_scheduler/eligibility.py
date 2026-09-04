"""The per-tick orchestration loop + who-needs-an-email query."""

from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.email_notify_settings import EmailNotifySettings

from .time_utils import ensure_timezone_aware


class EligibilityMixin:
    """process_daily_summaries (the scheduled job) + get_users_to_notify."""

    async def process_daily_summaries(self) -> None:
        """
        Process and send daily summary emails for all users who need them.
        This function runs every 15 minutes and checks which users need emails
        based on their routine settings and last_email_notify_time.
        """
        try:
            current_time = datetime.now(timezone.utc)
            print(f"🔄 [SCHEDULER] ===== STARTING PROCESS ===== at {current_time}")
            print(f"🔄 [SCHEDULER] Scheduler is_running: {self.is_running}")

            # Get database session
            async with AsyncSessionLocal() as db:
                print(f"🔄 [SCHEDULER] Database session created")
                try:
                    # Get all users with enabled email notifications
                    users_to_notify = await self.get_users_to_notify(db)

                    print(f"📧 [SCHEDULER] Found {len(users_to_notify)} users to notify")

                    # Process each user
                    for user_settings in users_to_notify:
                        try:
                            await self.send_daily_summary_email(user_settings, db)
                        except Exception as e:
                            print(f"❌ Error sending email to user {user_settings.resource_id}: {e}")
                            continue

                    print(f"✅ Finished processing daily summary emails")

                except Exception as e:
                    print(f"❌ Error in process_daily_summaries: {e}")
                    import traceback
                    print(traceback.format_exc())

        except Exception as e:
            print(f"❌ Error in process_daily_summaries: {e}")
            import traceback
            print(traceback.format_exc())

    async def get_users_to_notify(self, db: AsyncSession) -> List[EmailNotifySettings]:
        """
        Get list of users who need to receive daily summary emails.

        Criteria:
        - is_notification_enabled = 1
        - routine is set (not None)
        - Either last_email_notify_time is None OR
          (current_time - last_email_notify_time) >= routine minutes
        """
        now = datetime.now(timezone.utc)

        # Get all enabled notification settings
        stmt = select(EmailNotifySettings).where(
            EmailNotifySettings.is_notification_enabled == 1,
            EmailNotifySettings.routine.isnot(None)
        )
        result = await db.execute(stmt)
        all_settings = result.scalars().all()

        print(f"🔍 [SCHEDULER] Found {len(all_settings)} total users with notifications enabled")

        users_to_notify = []

        for setting in all_settings:
            # Check if user needs notification
            if setting.last_email_notify_time is None:
                # First time - last_email_notify_time is NULL, send email now
                print(f"🔍 [SCHEDULER] User {setting.resource_id}: First time (last_email_notify_time is NULL) - WILL NOTIFY")
                users_to_notify.append(setting)
            else:
                # Ensure timezone-aware datetime for comparison
                last_notify_time = ensure_timezone_aware(setting.last_email_notify_time)
                # Calculate time difference
                time_diff = now - last_notify_time
                routine_minutes = setting.routine

                # Check if enough time has passed
                if time_diff >= timedelta(minutes=routine_minutes):
                    print(f"🔍 [SCHEDULER] User {setting.resource_id}: Time passed ({time_diff.total_seconds()/60:.1f} mins) >= routine ({routine_minutes} mins) - WILL NOTIFY")
                    users_to_notify.append(setting)
                else:
                    remaining = timedelta(minutes=routine_minutes) - time_diff
                    print(f"🔍 [SCHEDULER] User {setting.resource_id}: Not yet time (need {routine_minutes} mins, have {time_diff.total_seconds()/60:.1f} mins, remaining {remaining.total_seconds()/60:.1f} mins)")

        return users_to_notify
