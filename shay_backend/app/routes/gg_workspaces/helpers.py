"""
Shared helpers for the gg_workspaces package: UUID coercion, workspace
lookup, and the two response-shaping functions used by both the members
and app-connections sub-modules.

Split from app/routes/gg_workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gg_app_connections import GGAppConnection
from app.models.member import GGMember
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.gg_workspace import (
    GGWorkspaceAppConnectionResponse,
    GGWorkspaceConnectorMetadata,
    GGWorkspaceMemberResponse,
)


def _to_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {name} format")


def _member_resp(m: GGMember, user: Optional[User] = None) -> GGWorkspaceMemberResponse:
    return GGWorkspaceMemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        workspace_id=str(m.workspace_id),
        level=m.level,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
        name=user.name if user else None,
        email=user.email_id if user else None,
    )


def _conn_resp(conn: GGAppConnection, connector: Optional[User] = None) -> GGWorkspaceAppConnectionResponse:
    return GGWorkspaceAppConnectionResponse(
        id=str(conn.id),
        app_id=str(conn.app_id) if conn.app_id else None,
        workspace_id=str(conn.workspace_id),
        level=conn.level,
        connected_by=str(conn.connected_by),
        connector=GGWorkspaceConnectorMetadata(
            user_id=str(connector.id),
            name=connector.name,
            email_id=connector.email_id,
            avatar_url=connector.avatar_url,
        ) if connector else None,
        connection_name=conn.connection_name,
        connection_status=conn.connection_status,
        connection_settings=conn.connection_settings,
        webhook_url=conn.webhook_url,
        callback_url=conn.callback_url,
        is_active=conn.is_active,
        auto_sync=conn.auto_sync,
        sync_interval=conn.sync_interval,
        last_sync_at=conn.last_sync_at,
        sync_status=conn.sync_status,
        error_message=conn.error_message,
        provider=conn.provider,
        provider_account_id=conn.provider_account_id,
        auth_type=conn.auth_type,
        last_token_refresh=conn.last_token_refresh,
        token_expires_at=conn.token_expires_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _get_workspace_or_404(db: AsyncSession, ws_uuid: UUID) -> Workspace:
    ws = (await db.execute(select(Workspace).where(Workspace.id == ws_uuid))).scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws
