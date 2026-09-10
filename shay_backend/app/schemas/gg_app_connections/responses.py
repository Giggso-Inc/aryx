"""
GGAppConnection response/list schemas.

Split out of the former app/schemas/gg_app_connections.py to keep each
file under the Raven 150-line style limit.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ConnectorMetadata(BaseModel):
    """Metadata about the user who connected the app."""

    user_id:    str
    name:       Optional[str] = None
    email_id:   Optional[str] = None
    avatar_url: Optional[str] = None


class GGAppConnectionResponse(BaseModel):
    """Schema for GGAppConnection response."""

    id:                  str
    app_id:              Optional[str]          = None
    level:               str
    workspace_id:        Optional[str]          = None
    channel_id:          Optional[str]          = None
    thread_id:           Optional[str]          = None
    connected_by:        str
    connector:           Optional[ConnectorMetadata] = None

    connection_name:     Optional[str]          = None
    connection_status:   str
    connection_settings: Optional[Dict[str, Any]] = None
    webhook_url:         Optional[str]          = None
    callback_url:        Optional[str]          = None
    is_active:           bool
    auto_sync:           bool
    sync_interval:       int
    last_sync_at:        Optional[datetime]     = None
    sync_status:         Optional[str]          = None
    error_message:       Optional[str]          = None

    provider:            Optional[str]          = None
    provider_account_id: Optional[str]          = None
    auth_type:           Optional[str]          = None
    last_token_refresh:  Optional[datetime]     = None
    token_expires_at:    Optional[datetime]     = None

    created_at:          Optional[datetime]     = None
    updated_at:          Optional[datetime]     = None

    class Config:
        from_attributes = True


class GGAppConnectionList(BaseModel):
    """Paginated list of GGAppConnections."""

    connections: List[GGAppConnectionResponse]
    total:       int
    page:        int
    size:        int
    pages:       int
