"""
Pydantic schemas for GGAppConnection — unified app connections across
workspace / channel / thread scopes.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID
import json

from pydantic import BaseModel, Field, field_validator, model_validator


ScopeLevel = Literal["workspace", "channel", "thread"]


class GGAppConnectionCreate(BaseModel):
    """Schema for creating a new GGAppConnection at any scope level."""

    app_id:      UUID
    level:       ScopeLevel    = Field("channel", description="workspace | channel | thread")
    workspace_id: Optional[UUID] = Field(None, description="Set when level='workspace'")
    channel_id:  Optional[UUID] = Field(None, description="Set when level='channel'")
    thread_id:   Optional[UUID] = Field(None, description="Set when level='thread'")

    connection_name:     Optional[str]  = Field(None, max_length=255)
    connection_status:   str            = Field("active", description="active | inactive | error | connected | disconnected | pending")
    connection_settings: Optional[Union[str, Dict[str, Any]]] = None
    webhook_url:         Optional[str]  = Field(None, max_length=500)
    callback_url:        Optional[str]  = Field(None, max_length=500)
    is_active:           bool           = True
    auto_sync:           bool           = False
    sync_interval:       int            = Field(3600, ge=60)
    provider:            Optional[str]  = None
    auth_type:           Optional[str]  = "oauth2"

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

    @model_validator(mode="after")
    def validate_exclusive_arc(self) -> "GGAppConnectionCreate":
        scope_set = sum([
            self.workspace_id is not None,
            self.channel_id   is not None,
            self.thread_id    is not None,
        ])
        if scope_set != 1:
            raise ValueError(
                "Exactly one of workspace_id, channel_id, thread_id must be provided."
            )
        level_map: Dict[str, Optional[UUID]] = {
            "workspace": self.workspace_id,
            "channel":   self.channel_id,
            "thread":    self.thread_id,
        }
        if level_map[self.level] is None:
            raise ValueError(
                f"level='{self.level}' but the corresponding ID field is not set."
            )
        return self


class GGAppConnectionUpdate(BaseModel):
    """Schema for updating an existing GGAppConnection."""

    connection_name:     Optional[str]  = Field(None, max_length=255)
    connection_status:   Optional[str]  = None
    connection_settings: Optional[Union[str, Dict[str, Any]]] = None
    webhook_url:         Optional[str]  = Field(None, max_length=500)
    callback_url:        Optional[str]  = Field(None, max_length=500)
    is_active:           Optional[bool] = None
    auto_sync:           Optional[bool] = None
    sync_interval:       Optional[int]  = Field(None, ge=60)
    sync_status:         Optional[str]  = None
    error_message:       Optional[str]  = None
    provider:            Optional[str]  = None
    auth_type:           Optional[str]  = None
    provider_account_id: Optional[str]  = None
    last_token_refresh:  Optional[datetime] = None
    token_expires_at:    Optional[datetime] = None

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
