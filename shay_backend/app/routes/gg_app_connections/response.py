"""Response-building helper shared by every gg_app_connections submodule."""

from typing import Optional

from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import ConnectorMetadata, GGAppConnectionResponse


def build_response(conn: GGAppConnection, connector: Optional[User] = None) -> GGAppConnectionResponse:
    return GGAppConnectionResponse(
        id=str(conn.id),
        app_id=str(conn.app_id) if conn.app_id else None,
        level=conn.level,
        workspace_id=str(conn.workspace_id) if conn.workspace_id else None,
        channel_id=str(conn.channel_id)     if conn.channel_id   else None,
        thread_id=str(conn.thread_id)       if conn.thread_id    else None,
        connected_by=str(conn.connected_by),
        connector=ConnectorMetadata(
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
