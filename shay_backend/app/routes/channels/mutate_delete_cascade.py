"""
Cascading-delete steps for delete_channel, split out of mutate_delete.py in
wave B3 of the Raven style-compliance line-count pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to bring mutate_delete.py
under 150 lines.

Deletes every record that references a channel, in dependency order, before
the channel row itself is deleted. Caller (mutate_delete.delete_channel) owns
the transaction: it wraps this call in try/except and commits/rolls back.
"""

from sqlalchemy import select, func, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_member import ChannelMember
from app.models.app_account import AppAccount
from app.models.datasource import Datasource
from app.models.task import Task
from app.models.approval import Approval


async def cascade_delete_channel_data(db: AsyncSession, channel, channel_uuid) -> None:
    """Delete all records that reference `channel_uuid`, then the channel
    itself. Does not commit — caller owns the transaction."""
    from app.models.message import Thread, Message
    from app.models.attachment import Attachment

    # 1. Delete approvals first (they reference thread_id and message_id; no task_id)
    approvals_stmt = select(Approval).where(Approval.channel_id == channel_uuid)
    approvals = (await db.execute(approvals_stmt)).scalars().all()
    for approval in approvals:
        await db.delete(approval)

    # 2. Delete messages associated with this channel
    messages_stmt = select(Message).where(Message.channel_id == channel_uuid)
    messages = (await db.execute(messages_stmt)).scalars().all()
    for message in messages:
        await db.delete(message)

    # 3. Delete threads associated with this channel
    threads_stmt = select(Thread).where(Thread.channel_id == channel_uuid)
    threads = (await db.execute(threads_stmt)).scalars().all()
    for thread in threads:
        await db.delete(thread)

    # 4. Delete attachments associated with this channel
    attachments_stmt = select(Attachment).where(Attachment.channel_id == channel_uuid)
    attachments = (await db.execute(attachments_stmt)).scalars().all()
    for attachment in attachments:
        await db.delete(attachment)

    # 5. Delete tasks associated with this channel
    tasks_stmt = select(Task).where(Task.channel_id == channel_uuid)
    tasks = (await db.execute(tasks_stmt)).scalars().all()
    for task in tasks:
        await db.delete(task)

    # 6. Delete email_sync/message_sync records that reference app_accounts
    # before deleting app_accounts
    app_accounts_stmt = select(AppAccount.id).where(AppAccount.channel_id == channel_uuid)
    app_account_ids = [row[0] for row in (await db.execute(app_accounts_stmt)).all()]

    if app_account_ids:
        for app_account_id in app_account_ids:
            await db.execute(
                text("DELETE FROM gg_email_sync WHERE app_account_id = :app_account_id"),
                {'app_account_id': app_account_id},
            )
            await db.execute(
                text("DELETE FROM gg_message_sync WHERE app_account_id = :app_account_id"),
                {'app_account_id': app_account_id},
            )
        # Flush to ensure sync records are deleted before app_accounts deletion
        await db.flush()

    # 7. Delete app accounts connected to this channel
    app_accounts_stmt = select(AppAccount).where(AppAccount.channel_id == channel_uuid)
    app_accounts = (await db.execute(app_accounts_stmt)).scalars().all()
    for app_account in app_accounts:
        await db.delete(app_account)

    # 8. Delete data sources associated with this channel
    datasources_stmt = select(Datasource).where(Datasource.channel_id == channel_uuid)
    datasources = (await db.execute(datasources_stmt)).scalars().all()
    for datasource in datasources:
        await db.delete(datasource)

    # 9. Delete channel members (direct SQL delete)
    members_count_stmt = select(func.count(ChannelMember.id)).where(ChannelMember.channel_id == channel_uuid)
    members_count = (await db.execute(members_count_stmt)).scalar()
    print(f"Found {members_count} channel members to delete for channel {channel_uuid}")

    delete_members_stmt = delete(ChannelMember).where(ChannelMember.channel_id == channel_uuid)
    members_delete_result = await db.execute(delete_members_stmt)
    print(f"Deleted {members_delete_result.rowcount} channel members")

    # Force flush to ensure the deletes are applied
    await db.flush()

    # Finally delete the channel itself
    await db.delete(channel)
