"""
Shared query-building helpers for list_my.list_channels — split out to bring
list_my.py under the 150-line limit (docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from sqlalchemy import select, func, and_, String

from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember


def apply_common_filters(query, user, search, workspace_tag, is_archived, channel_type):
    query = query.where(
        and_(
            Channel.company_id == user.company_id,
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True,
        )
    )
    if search:
        query = query.where(Channel.name.ilike(f"%{search}%"))
    if workspace_tag:
        query = query.where(Workspace.name == workspace_tag)
    query = query.where(Channel.is_archived == is_archived)
    if channel_type:
        query = query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())
    return query


def apply_sort(query, sort_by, sort_order):
    # NOTE: the "last_message_at" branch and the default (else) branch use
    # different fallback columns (updated_at vs created_at) in the original
    # code — preserved exactly here rather than merged, even though
    # sort_by defaults to "last_message_at" so the else branch is rarely hit.
    asc = (sort_order or "").lower() == "asc"
    if sort_by == "name":
        return query.order_by(Channel.name.asc() if asc else Channel.name.desc())
    if sort_by == "last_message_at":
        col = func.coalesce(Channel.last_message_at, Channel.updated_at)
        return query.order_by(col.asc() if asc else col.desc())
    if sort_by == "message_count":
        return query.order_by(Channel.message_count.asc() if asc else Channel.message_count.desc())
    col = func.coalesce(Channel.last_message_at, Channel.created_at)
    return query.order_by(col.asc() if asc else col.desc())


async def has_archived_channels(db, user, search, workspace_tag, channel_type, is_archived) -> bool:
    """When listing active channels, check if the user has any archived
    channels at all, for the "Show archived" tab. Not needed (and always
    True) when already viewing the archived list — callers short-circuit
    that case with `is_archived or ...` before calling this."""
    if is_archived:
        return True
    query = select(func.count(Channel.id)).join(
        Workspace, Channel.workspace_id == Workspace.id
    ).join(ChannelMember, Channel.id == ChannelMember.channel_id).where(
        and_(
            Channel.company_id == user.company_id,
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True,
            Channel.is_archived == True,
        )
    )
    if search:
        query = query.where(Channel.name.ilike(f"%{search}%"))
    if workspace_tag:
        query = query.where(Workspace.name == workspace_tag)
    if channel_type:
        query = query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())
    return ((await db.execute(query)).scalar() or 0) > 0
