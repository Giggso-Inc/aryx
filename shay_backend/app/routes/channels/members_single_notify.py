"""
New-member email notification for add_channel_member, split out of
members_single.py in wave B3 of the Raven style-compliance line-count pass
(see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to bring
members_single.py under 150 lines.
"""

from app.core.config import settings
from app.services.email_service import email_service
from .helpers import get_channel_admins


async def notify_new_member(channel, user, current_user, body, db) -> None:
    """Email: Accsell/Zaptag -> requirement flow only (added user, View
    Channel); others -> previous flow (notify channel admins). Errors here
    are logged but never fail the member addition itself."""
    try:
        # [DEBUG] Log raw body value so we can verify platform_name/platformName from request
        platform_name = body.platform_name or settings.PLATFORM_NAME
        platform_lower = str(platform_name or '').strip().lower()
        print(f"📧 [channel add-member] body.platform_name={body.platform_name!r}, resolved platform_name={platform_name!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}")
        if platform_lower in ('accsell', 'zaptag'):
            # Accsell/Zaptag: send only to the added user with "You have been added" + View Channel button (requirement flow)
            notification_data_user = {
                'channel_id': str(channel.id),
                'channel_name': channel.name,
                'user_name': user.name or user.email_id.split('@')[0],
                'user_email': user.email_id,
                'user_role': body.role,
                'added_by': current_user.name or current_user.email_id.split('@')[0],
                'platform_name': platform_name,
                'send_to_added_user': True
            }
            # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
            base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == 'accsell' else settings.PLATFORM_URL
            # [DEBUG] Confirm payload before calling email service
            print(f"📧 [channel add-member] Sending to added user: to_emails=[{user.email_id}], notification_data keys={list(notification_data_user.keys())}, send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
            email_sent_user = email_service.send_channel_member_notification(
                to_emails=[user.email_id],
                notification_data=notification_data_user,
                platform_url=base_url
            )
            if email_sent_user:
                print(f"✅ Channel member notification (added user) sent to {user.email_id}")
            else:
                print(f"⚠️ Channel member notification (added user) failed to send")
        else:
            # Previous flow: send email notification to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
            print(f"📧 Preparing to notify channel admins about new member {user.email_id}...")
            channel_admins = await get_channel_admins(channel.id, db)
            if channel_admins:
                admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                if admin_emails:
                    # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                    notification_data = {
                        'channel_name': channel.name,
                        'user_name': user.name or user.email_id.split('@')[0],
                        'user_email': user.email_id,
                        'user_role': body.role,
                        'added_by': current_user.name or current_user.email_id.split('@')[0],
                        'platform_name': platform_name
                    }
                    email_sent = email_service.send_channel_member_notification(
                        to_emails=admin_emails,
                        notification_data=notification_data,
                        platform_url=settings.PLATFORM_URL
                    )
                    if email_sent:
                        print(f"✅ Channel member notification emails sent successfully to {len(admin_emails)} admins")
                    else:
                        print(f"⚠️ Some channel member notification emails failed to send")
            else:
                print(f"ℹ️ No channel admins found to notify")
    except Exception as email_error:
        # Log email error but don't fail the member addition
        print(f"⚠️ Error sending channel member notification (non-critical): {email_error}")
        import traceback
        print(f"📋 Email error traceback: {traceback.format_exc()}")
