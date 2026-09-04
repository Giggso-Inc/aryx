"""
Background email notification helpers for the approval workflow.

Stated exception to the 150-line target: these five helpers form one
notification pipeline (member-eligibility lookup -> template render ->
send, and two background-task drivers that each open their own DB
session) that share the same template-loading/email-sending pattern for
the "approval created" and "approval reassigned" cases. Splitting them
into separate files would fragment the pipeline across more modules
without reducing the coupling between them, so they are kept together
per the Raven Style Compliance Plan's "too tightly coupled to split
further safely" carve-out (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import List
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.services.email_service import email_service
from app.models.realtime_notification import RealtimeNotification
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.user import User


async def get_channel_members_with_approval_notifications_enabled(
    channel_id: UUID,
    approval_creator_id: UUID,
    db: AsyncSession
) -> List[User]:
    """
    Get all channel members who have approval notifications enabled.
    Excludes the approval creator.

    Logic:
    - Get all active channel members
    - For each member, check gg_realtime_notification table
    - Only include if:
      1. Data exists in table
      2. is_notifications_enabled = true
      3. is_approval_enabled = true
    - Exclude approval creator

    Args:
        channel_id: Channel ID
        approval_creator_id: User ID who created the approval (will be excluded)
        db: Database session

    Returns:
        List of User objects who have approval notifications enabled
    """
    # Get all active channel members
    channel_members_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.is_active == True
        )
    )
    channel_members_result = await db.execute(channel_members_stmt)
    channel_members = channel_members_result.scalars().all()

    if not channel_members:
        return []

    # Get user IDs from channel members
    member_user_ids = [member.user_id for member in channel_members]

    # Get notification preferences for all members in this channel
    notification_prefs_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.channel_id == channel_id,
            RealtimeNotification.user_id.in_(member_user_ids)
        )
    )
    notification_prefs_result = await db.execute(notification_prefs_stmt)
    notification_prefs = notification_prefs_result.scalars().all()

    # Create a map of user_id -> notification preference
    notification_map = {pref.user_id: pref for pref in notification_prefs}

    # Filter members who have notifications enabled
    enabled_user_ids = []
    for member in channel_members:
        # Skip approval creator
        if member.user_id == approval_creator_id:
            continue

        # Check if notification preference exists
        notification_pref = notification_map.get(member.user_id)

        # Only send if data exists AND both flags are enabled
        if notification_pref:
            if notification_pref.is_notifications_enabled and notification_pref.is_approval_enabled:
                enabled_user_ids.append(member.user_id)

    if not enabled_user_ids:
        return []

    # Get user details for enabled members
    users_stmt = select(User).where(User.id.in_(enabled_user_ids))
    users_result = await db.execute(users_stmt)
    users = users_result.scalars().all()

    return list(users)


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


async def process_approval_reassignment_notifications(
    reassigner_id: str,
    reassigned_approver_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval reassignment notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        reassigner_id: UUID string of the user who reassigned the approval
        reassigned_approver_id: UUID string of the user reassigned to approve
        channel_id: UUID string of the channel where approval was reassigned
        redirect_url: Pre-constructed URL to redirect to view the approval
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get reassigner
            reassigner_stmt = select(User).where(User.id == UUID(reassigner_id))
            reassigner_result = await db.execute(reassigner_stmt)
            reassigner = reassigner_result.scalar_one_or_none()

            if not reassigner:
                print(f"⚠️ Reassigner not found: {reassigner_id}")
                return

            # Get reassigned approver
            approver_stmt = select(User).where(User.id == UUID(reassigned_approver_id))
            approver_result = await db.execute(approver_stmt)
            reassigned_approver = approver_result.scalar_one_or_none()

            if not reassigned_approver:
                print(f"⚠️ Reassigned approver not found: {reassigned_approver_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Get channel members with approval notifications enabled
            enabled_members = await get_channel_members_with_approval_notifications_enabled(
                channel.id,
                reassigner.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_reassignment_notification_email(
                    member,
                    reassigner,
                    reassigned_approver,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing approval reassignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


async def process_approval_notifications(
    approval_creator_id: str,
    approver_user_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        approval_creator_id: UUID string of the user who created the approval
        approver_user_id: UUID string of the user who needs to approve
        channel_id: UUID string of the channel where approval was created
        redirect_url: Pre-constructed URL to redirect to view the approval
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get approval creator
            creator_stmt = select(User).where(User.id == UUID(approval_creator_id))
            creator_result = await db.execute(creator_stmt)
            approval_creator = creator_result.scalar_one_or_none()

            if not approval_creator:
                print(f"⚠️ Approval creator not found: {approval_creator_id}")
                return

            # Get approver user
            approver_stmt = select(User).where(User.id == UUID(approver_user_id))
            approver_result = await db.execute(approver_stmt)
            approver_user = approver_result.scalar_one_or_none()

            if not approver_user:
                print(f"⚠️ Approver user not found: {approver_user_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Get channel members with approval notifications enabled
            enabled_members = await get_channel_members_with_approval_notifications_enabled(
                channel.id,
                approval_creator.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_notification_email(
                    member,
                    approval_creator,
                    approver_user,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing approval notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
