"""
Aggregate count/sum helpers for fetch_company_subscription_details: user,
workspace, channel, AI-response, storage, and shared-inbox counts for a
company. Extracted from subscription_details.py.
"""
from typing import Any, Tuple

from sqlalchemy import select, func, join
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.ai_response import AIResponse
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.app_account import AppAccount


async def _fetch_user_counts(db: AsyncSession, company_id: Any) -> Tuple[int, int]:
    """Return (admin_count, user_count) for the company."""
    admin_count_result = await db.execute(
        select(func.count(User.id)).where(
            User.company_id == company_id,
            User.role == "admin"
        )
    )
    admin_count = admin_count_result.scalar() or 0

    user_count_result = await db.execute(
        select(func.count(User.id)).where(
            User.company_id == company_id,
            User.role != "admin"
        )
    )
    user_count = user_count_result.scalar() or 0
    return admin_count, user_count


async def _fetch_workspace_count(db: AsyncSession, company_id: Any) -> int:
    result = await db.execute(
        select(func.count(Workspace.id)).where(Workspace.company_id == company_id)
    )
    return result.scalar() or 0


async def _fetch_channel_count(db: AsyncSession, company_id: Any) -> int:
    result = await db.execute(
        select(func.count(Channel.id)).where(Channel.company_id == company_id)
    )
    return result.scalar() or 0


async def _fetch_ai_response_count(db: AsyncSession, company_id: Any) -> int:
    """Count AI responses for company's workspaces."""
    workspace_ids_result = await db.execute(
        select(Workspace.id).where(Workspace.company_id == company_id)
    )
    workspace_ids = [w for w in workspace_ids_result.scalars().all()]

    if not workspace_ids:
        return 0

    ai_response_count_result = await db.execute(
        select(func.count(AIResponse.id)).where(AIResponse.workspace_id.in_(workspace_ids))
    )
    return ai_response_count_result.scalar() or 0


async def _fetch_storage_totals(db: AsyncSession, company_id: Any) -> int:
    """Sum of attachment sizes from gg_attachments and gg_email_attachments."""
    attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
            Attachment.channel_id.in_(
                select(Channel.id).where(Channel.company_id == company_id)
            )
        )
    )
    attachment_size = attachment_size_result.scalar() or 0

    email_attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(EmailAttachment.file_size), 0)).where(
            EmailAttachment.channel_id.in_(
                select(Channel.id).where(Channel.company_id == company_id)
            )
        )
    )
    email_attachment_size = email_attachment_size_result.scalar() or 0

    return attachment_size + email_attachment_size


async def _fetch_shared_inbox_count(db: AsyncSession, company_id: Any) -> int:
    """Count distinct channels that have active email app accounts."""
    result = await db.execute(
        select(func.count(func.distinct(Channel.id)))
        .select_from(join(Channel, AppAccount, Channel.id == AppAccount.channel_id))
        .where(
            Channel.company_id == company_id,
            AppAccount.api_key == 'email',
            AppAccount.is_active == True
        )
    )
    return result.scalar() or 0
