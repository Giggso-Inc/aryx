"""
Scope-aware resolution helpers for GGAppConnection.

Uses the gg_app_connections table (exclusive arc pattern) to return the
most specific active connection for a given scope.

Inheritance direction: thread > channel > workspace (most specific wins).
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gg_app_connections import GGAppConnection
from app.models.app import App


async def resolve_gg_app_connection(
    db: AsyncSession,
    app_key: str,
    *,
    thread_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
) -> Optional[GGAppConnection]:
    """
    Return the most specific active GGAppConnection for a given scope + app_key.
    Resolution order: thread → channel → workspace (most specific wins).
    Returns None if no active connection is found at any level.
    """
    scopes = []
    if thread_id:
        scopes.append(("thread", "thread_id", thread_id))
    if channel_id:
        scopes.append(("channel", "channel_id", channel_id))
    if workspace_id:
        scopes.append(("workspace", "workspace_id", workspace_id))

    for level, fk_field, fk_value in scopes:
        stmt = (
            select(GGAppConnection)
            .join(App, App.id == GGAppConnection.app_id)
            .where(
                and_(
                    App.app_key == app_key,
                    GGAppConnection.is_active == True,
                    GGAppConnection.connection_status == "active",
                    GGAppConnection.level == level,
                    getattr(GGAppConnection, fk_field) == fk_value,
                )
            )
        )
        result = await db.execute(stmt)
        conn = result.scalar_one_or_none()
        if conn:
            return conn

    return None


async def get_all_connections_for_scope(
    db: AsyncSession,
    *,
    thread_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
) -> List[GGAppConnection]:
    """
    Return all active GGAppConnections visible at the given scope, including
    inherited ones from parent scopes (no deduplication by app_key).
    """
    conditions = []
    if thread_id:
        conditions.append(
            and_(GGAppConnection.level == "thread", GGAppConnection.thread_id == thread_id)
        )
    if channel_id:
        conditions.append(
            and_(GGAppConnection.level == "channel", GGAppConnection.channel_id == channel_id)
        )
    if workspace_id:
        conditions.append(
            and_(GGAppConnection.level == "workspace", GGAppConnection.workspace_id == workspace_id)
        )

    if not conditions:
        return []

    stmt = select(GGAppConnection).where(
        and_(
            GGAppConnection.is_active == True,
            or_(*conditions),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
