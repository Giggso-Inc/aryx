"""
Schemas for workspace-level GGMember and GGAppConnection operations.

The workspace_id is always taken from the URL — the request body never
needs to repeat it. These schemas are narrower versions of the generic
member / app-connection schemas, scoped to workspace operations only.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import json

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Member schemas
# ---------------------------------------------------------------------------

class GGWorkspaceMemberCreate(BaseModel):
    """Body for adding a member at workspace scope."""

    user_id:     UUID
    role:        str                       = Field("member", description="member | admin | viewer")
    permissions: Optional[Dict[str, Any]] = None
    invited_by:  Optional[UUID]           = None


class GGWorkspaceMemberUpdate(BaseModel):
    """Body for updating an existing workspace membership."""

    role:        Optional[str]             = None
    is_active:   Optional[bool]            = None
    permissions: Optional[Dict[str, Any]] = None


class GGWorkspaceMemberResponse(BaseModel):
    """Response for a single workspace GGMember."""

    id:           str
    user_id:      str
    workspace_id: str
    level:        str = "workspace"
    role:         str
    is_active:    bool
    permissions:  Optional[Dict[str, Any]] = None
    invited_by:   Optional[str]            = None
    joined_at:    Optional[datetime]       = None
    created_at:   Optional[datetime]       = None
    updated_at:   Optional[datetime]       = None
    name:         Optional[str]            = None
    email:        Optional[str]            = None

    class Config:
        from_attributes = True


class GGWorkspaceMemberList(BaseModel):
    """Paginated list of workspace GGMembers."""

    members: List[GGWorkspaceMemberResponse]
    total:   int
    page:    int
    size:    int
    pages:   int


# ---------------------------------------------------------------------------
# App-connection schemas
# ---------------------------------------------------------------------------

class GGWorkspaceAppConnectionCreate(BaseModel):
    """
    Body for connecting an app at workspace scope.
    workspace_id is taken from the URL — not required in the body.
    """

    app_id:              UUID
    connection_name:     Optional[str]             = Field(None, max_length=255)
    connection_status:   str                       = Field("active", description="active | inactive | error | pending")
    connection_settings: Optional[Union[str, Dict[str, Any]]] = None
    webhook_url:         Optional[str]             = Field(None, max_length=500)
    callback_url:        Optional[str]             = Field(None, max_length=500)
    is_active:           bool                      = True
    auto_sync:           bool                      = False
    sync_interval:       int                       = Field(3600, ge=60)
    provider:            Optional[str]             = None
    auth_type:           Optional[str]             = "oauth2"

    @field_validator("connection_settings", mode="before")
    @classmethod
    def parse_connection_settings(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @field_validator("connection_status", mode="before")
    @classmethod
    def validate_status(cls, v):
        valid = {"active", "inactive", "error", "connected", "disconnected", "pending"}
        if v not in valid:
            raise ValueError(f"connection_status must be one of: {sorted(valid)}")
        return v


class GGWorkspaceAppConnectionUpdate(BaseModel):
    """Body for updating a workspace-level GGAppConnection."""

    connection_name:     Optional[str]             = Field(None, max_length=255)
    connection_status:   Optional[str]             = None
    connection_settings: Optional[Union[str, Dict[str, Any]]] = None
    webhook_url:         Optional[str]             = Field(None, max_length=500)
    callback_url:        Optional[str]             = Field(None, max_length=500)
    is_active:           Optional[bool]            = None
    auto_sync:           Optional[bool]            = None
    sync_interval:       Optional[int]             = Field(None, ge=60)
    sync_status:         Optional[str]             = None
    error_message:       Optional[str]             = None
    provider:            Optional[str]             = None
    auth_type:           Optional[str]             = None
    provider_account_id: Optional[str]             = None
    last_token_refresh:  Optional[datetime]        = None
    token_expires_at:    Optional[datetime]        = None

    @field_validator("connection_status", mode="before")
    @classmethod
    def validate_status(cls, v):
        if v is not None:
            valid = {"active", "inactive", "error", "connected", "disconnected"}
            if v not in valid:
                raise ValueError(f"connection_status must be one of: {sorted(valid)}")
        return v

    @field_validator("connection_settings", mode="before")
    @classmethod
    def parse_connection_settings(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return None


class GGWorkspaceConnectorMetadata(BaseModel):
    """Metadata about who connected the app."""

    user_id:    str
    name:       Optional[str] = None
    email_id:   Optional[str] = None
    avatar_url: Optional[str] = None


class GGWorkspaceAppConnectionResponse(BaseModel):
    """Response for a single workspace-level GGAppConnection."""

    id:                  str
    app_id:              Optional[str]                      = None
    workspace_id:        str
    level:               str                               = "workspace"
    connected_by:        str
    connector:           Optional[GGWorkspaceConnectorMetadata] = None
    connection_name:     Optional[str]                     = None
    connection_status:   str
    connection_settings: Optional[Dict[str, Any]]          = None
    webhook_url:         Optional[str]                     = None
    callback_url:        Optional[str]                     = None
    is_active:           bool
    auto_sync:           bool
    sync_interval:       int
    last_sync_at:        Optional[datetime]                = None
    sync_status:         Optional[str]                     = None
    error_message:       Optional[str]                     = None
    provider:            Optional[str]                     = None
    provider_account_id: Optional[str]                     = None
    auth_type:           Optional[str]                     = None
    last_token_refresh:  Optional[datetime]                = None
    token_expires_at:    Optional[datetime]                = None
    created_at:          Optional[datetime]                = None
    updated_at:          Optional[datetime]                = None

    class Config:
        from_attributes = True


class GGWorkspaceAppConnectionList(BaseModel):
    """Paginated list of workspace GGAppConnections."""

    connections: List[GGWorkspaceAppConnectionResponse]
    total:       int
    page:        int
    size:        int
    pages:       int
