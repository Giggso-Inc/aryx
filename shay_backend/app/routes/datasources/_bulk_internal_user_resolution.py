"""
User resolution for the internal/bulk per-item loop: use the channel's
connected email account owner when available, else fall back to the first
active user in the channel's company.

Private module: used only by _bulk_internal_create_item.py.
"""

import logging

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)


async def resolve_internal_bulk_user(thread, channel, db: AsyncSession):
    """Resolve the user to attribute an internal/bulk (email attachment) datasource to."""
    # Get user from channel's connected email account (AppAccount)
    # For email attachments, use the user who connected the email account to the channel
    user = None
    try:
        from app.models.app_account import AppAccount
        # Get the active email AppAccount for this channel
        app_account_stmt = select(AppAccount).where(
            and_(
                AppAccount.channel_id == thread.channel_id,
                AppAccount.api_key == "email",
                AppAccount.is_active == True
            )
        ).order_by(AppAccount.created_at.desc()).limit(1)
        app_account_result = await db.execute(app_account_stmt)
        app_account = app_account_result.scalar_one_or_none()

        if app_account and app_account.connected_by:
            # Use the user who connected the email account
            user_stmt = select(User).where(User.id == app_account.connected_by)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            logger.info(f"✅ Using connected email account user for attachment: user_id={app_account.connected_by}")
    except Exception as e:
        logger.warning(f"Could not get user from AppAccount: {str(e)}")

    # Fallback: Get first active user from channel's company if no AppAccount found
    if not user:
        user_stmt = select(User).where(and_(User.company_id == channel.company_id, User.is_active == True)).limit(1)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        logger.info(f"⚠️ Using fallback: first active user from company for attachment")

    return user
