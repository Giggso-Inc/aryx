"""
Email notification helper for the bulk-csv channel-members endpoint.

Split out of members_bulk.py during the Raven style-compliance line-count
pass (wave B2) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.

Note: `email_service` is a shared singleton instance imported from
app.services.email_service. tests/test_channels_characterization.py patches
`app.routes.channels.members_bulk.email_service.send_channel_member_notification`,
which patches the *attribute on that singleton object* — since this module
imports the same object, the patch takes effect here too regardless of
which module performs the call.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.channel_member import ChannelMember
from app.services.email_service import email_service
from .helpers import get_channel_admins


async def send_bulk_add_notifications(
    db: AsyncSession,
    channel,
    current_user,
    new_members: List[ChannelMember],
    platform_name: str,
) -> None:
    """Send email notifications for newly-added members.

    Accsell/Zaptag → requirement flow only (each added user gets an email
    with a View Channel button); other platforms → previous flow (notify
    channel admins). Email errors are logged but never raised — they must
    not fail the member addition itself.
    """
    if not new_members:
        return

    try:
        new_member_user_ids = [member.user_id for member in new_members]
        new_member_users_stmt = select(User).where(User.id.in_(new_member_user_ids))
        new_member_users_result = await db.execute(new_member_users_stmt)
        new_member_users = {u.id: u for u in new_member_users_result.scalars().all()}
        # [DEBUG] Log query param and resolved value for bulk add (platform_name from query)
        platform_name_value = platform_name or settings.PLATFORM_NAME
        platform_lower = str(platform_name_value or "").strip().lower()
        print(f"📧 [channel bulk-add] platform_name param={platform_name!r}, resolved={platform_name_value!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}, new_members_count={len(new_members)}")
        if platform_lower in ("accsell", "zaptag"):
            # Accsell/Zaptag: requirement flow only - send to each added user with "You have been added" + View Channel button
            for member in new_members:
                user = new_member_users.get(member.user_id)
                if user:
                    notification_data_user = {
                        "channel_id": str(channel.id),
                        "channel_name": channel.name,
                        "user_name": user.name or user.email_id.split("@")[0],
                        "user_email": user.email_id,
                        "user_role": member.role,
                        "added_by": current_user.name or current_user.email_id.split("@")[0],
                        "platform_name": platform_name_value,
                        "send_to_added_user": True
                    }
                    # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
                    base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == "accsell" else settings.PLATFORM_URL
                    # [DEBUG] Confirm payload before calling email service (bulk)
                    print(f"📧 [channel bulk-add] Sending to added user: to_emails=[{user.email_id}], send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
                    email_sent_user = email_service.send_channel_member_notification(
                        to_emails=[user.email_id],
                        notification_data=notification_data_user,
                        platform_url=base_url
                    )
                    if email_sent_user:
                        print(f"✅ Channel member notification (added user) sent to {user.email_id}")
                    else:
                        print("⚠️ Channel member notification (added user) failed to send")
        else:
            # Previous flow: send email notifications to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
            print(f"📧 Preparing to notify channel admins about {len(new_members)} new member(s)...")
            channel_admins = await get_channel_admins(channel.id, db)
            if channel_admins:
                admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                if admin_emails:
                    for member in new_members:
                        user = new_member_users.get(member.user_id)
                        if user:
                            # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                            notification_data = {
                                "channel_name": channel.name,
                                "user_name": user.name or user.email_id.split("@")[0],
                                "user_email": user.email_id,
                                "user_role": member.role,
                                "added_by": current_user.name or current_user.email_id.split("@")[0],
                                "platform_name": platform_name_value
                            }
                            email_sent = email_service.send_channel_member_notification(
                                to_emails=admin_emails,
                                notification_data=notification_data,
                                platform_url=settings.PLATFORM_URL
                            )
                            if email_sent:
                                print(f"✅ Channel member notification emails sent for {user.email_id}")
                            else:
                                print(f"⚠️ Failed to send channel member notification emails for {user.email_id}")
            else:
                print("ℹ️ No channel admins found to notify")
    except Exception as email_error:
        # Log email error but don't fail the member addition
        print(f"⚠️ Error sending channel member notifications (non-critical): {email_error}")
        import traceback
        print(f"📋 Email error traceback: {traceback.format_exc()}")
