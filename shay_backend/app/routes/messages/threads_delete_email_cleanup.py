"""
delete_thread sub-step: detect whether a thread's channel is email-backed,
and if so, clean up the related gg_email_* rows/tables.

Split out of app/routes/messages/threads_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

import logging

from sqlalchemy import select, and_, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.app_account import AppAccount

logger = logging.getLogger(__name__)


async def is_email_channel(db: AsyncSession, channel: Channel) -> bool:
    """Determine whether a channel is email-backed: either its channel_type
    says so directly, or it has an active email AppAccount (fallback for
    channels that don't set channel_type)."""
    if channel.channel_type is not None and str(channel.channel_type).strip().lower() == "email":
        return True

    email_acct = await db.execute(
        select(AppAccount).where(
            and_(
                AppAccount.channel_id == channel.id,
                AppAccount.api_key == "email",
                AppAccount.is_active == True,
            )
        ).limit(1)
    )
    return email_acct.scalar_one_or_none() is not None


async def cleanup_email_thread_data(db: AsyncSession, thread_id: str) -> None:
    """Unlink/clean up gg_email_attachments, gg_case_id, gg_emails, and
    gg_email_hash rows tied to a thread that's about to be deleted."""
    tid_uuid = thread_id

    # Get email_ids for this thread before we clear gg_emails.thread_id (for gg_email_hash fallback)
    email_ids_result = await db.execute(
        text("SELECT email_id FROM gg_emails WHERE thread_id = :tid"),
        {"tid": tid_uuid},
    )
    thread_email_ids = [row[0] for row in email_ids_result.fetchall() if row and row[0]]

    # 2. gg_email_attachments – DELETE where thread_id = <thread_id>
    await db.execute(text("DELETE FROM gg_email_attachments WHERE thread_id = :tid"), {"tid": tid_uuid})
    # 3. gg_case_id – DELETE where thread_id = <thread_id>
    await db.execute(text("DELETE FROM gg_case_id WHERE thread_id = :tid"), {"tid": tid_uuid})

    # 4. gg_emails – unlink and clear ml_processed_at only; leave thread_created true so scheduler doesn't treat as "needs thread"
    r_emails = await db.execute(
        text("UPDATE gg_emails SET thread_id = NULL, ml_processed_at = NULL WHERE thread_id = :tid"),
        {"tid": tid_uuid},
    )
    emails_updated = getattr(r_emails, "rowcount", None)
    if emails_updated is not None and emails_updated == 0:
        logger.warning("delete_thread: gg_emails UPDATE matched 0 rows for thread_id=%s", thread_id)
    else:
        logger.debug("delete_thread: gg_emails updated %s rows for thread_id=%s", emails_updated, thread_id)

    # 5. gg_email_hash – unlink and clear ml_processed (by thread_id; fallback by email_id if 0 rows)
    r_hash = await db.execute(
        text("UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE thread_id = :tid"),
        {"tid": tid_uuid},
    )
    hash_updated = getattr(r_hash, "rowcount", None)
    if hash_updated is not None and hash_updated == 0 and thread_email_ids:
        # Fallback: table may link by email_id only; update by this thread's email_ids
        stmt_hash_by_email = text(
            "UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE email_id IN :email_ids"
        ).bindparams(bindparam("email_ids", expanding=True))
        r_hash2 = await db.execute(stmt_hash_by_email, {"email_ids": thread_email_ids})
        hash_updated = getattr(r_hash2, "rowcount", None)
        logger.debug("delete_thread: gg_email_hash fallback by email_id updated %s rows for thread_id=%s", hash_updated, thread_id)
    if hash_updated is not None and hash_updated == 0:
        logger.warning("delete_thread: gg_email_hash UPDATE matched 0 rows for thread_id=%s", thread_id)
    else:
        logger.debug("delete_thread: gg_email_hash updated %s rows for thread_id=%s", hash_updated, thread_id)
