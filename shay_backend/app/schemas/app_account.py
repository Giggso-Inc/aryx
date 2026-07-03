"""
Pydantic schemas for AppAccount management
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
import uuid
import json


class AppAccountBase(BaseModel):
    """Base schema for AppAccount"""
    app_id: str = Field(..., description="ID of the app")
    channel_id: str = Field(..., description="ID of the channel")
    connection_name: Optional[str] = Field(None, max_length=255, description="Name for this connection")
    connection_status: str = Field("active", description="Status of the connection")
    connection_settings: Optional[Union[str, Dict[str, Any]]] = Field(None, description="JSON string or object for connection settings")
    webhook_url: Optional[str] = Field(None, max_length=500, description="Webhook URL for the app")
    callback_url: Optional[str] = Field(None, max_length=500, description="Callback URL for the app")
    is_active: bool = Field(True, description="Whether the connection is active")
    auto_sync: bool = Field(False, description="Whether to auto-sync with the app")
    sync_interval: int = Field(3600, ge=60, description="Sync interval in seconds")
    
    @validator('connection_settings', pre=True)
    def parse_connection_settings(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                # Try to parse JSON string
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                # If invalid JSON, return None
                return None
        return None


class AppAccountCreate(AppAccountBase):
    """Schema for creating a new app account"""
    
    @validator('app_id', 'channel_id')
    def validate_ids(cls, v):
        if not v or not v.strip():
            raise ValueError('ID cannot be empty')
        return v.strip()
    
    @validator('connection_status')
    def validate_status(cls, v):
        valid_statuses = ['active', 'inactive', 'error']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {valid_statuses}')
        return v


class AppAccountUpdate(BaseModel):
    """Schema for updating an app account"""
    connection_name: Optional[str] = Field(None, max_length=255)
    connection_status: Optional[str] = None
    connection_settings: Optional[Union[str, Dict[str, Any]]] = None
    webhook_url: Optional[str] = Field(None, max_length=500)
    callback_url: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    auto_sync: Optional[bool] = None
    sync_interval: Optional[int] = Field(None, ge=60)
    sync_status: Optional[str] = None
    error_message: Optional[str] = None
    
    @validator('connection_status')
    def validate_status(cls, v):
        if v is not None:
            valid_statuses = ['active', 'inactive', 'error']
            if v not in valid_statuses:
                raise ValueError(f'Status must be one of: {valid_statuses}')
        return v


class UserMetadata(BaseModel):
    """Schema for user metadata in app account response (who connected the app)"""
    email_id: Optional[str] = Field(None, description="Email of the user who connected")
    name: Optional[str] = Field(None, description="Name of the user who connected")
    user_id: Optional[str] = Field(None, description="User ID (same as connected_by)")
    avatar_url: Optional[str] = Field(None, description="Avatar URL of the user from DB")


class AppAccountResponse(AppAccountBase):
    """Schema for app account response"""
    id: str
    connected_by: str
    user_metadata: Optional[UserMetadata] = Field(None, description="Metadata of user who connected (email_id, name, user_id, avatar_url)")
    last_sync_at: Optional[datetime] = None
    sync_status: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AppAccountList(BaseModel):
    """Schema for list of app accounts"""
    app_accounts: List[AppAccountResponse]
    total: int
    page: int
    size: int
    pages: int


class AppAccountStats(BaseModel):
    """Schema for app account statistics"""
    total_connections: int
    active_connections: int
    error_connections: int
    apps_connected: List[str]
    channels_connected: List[str]
    recent_connections: List[AppAccountResponse]


class AppConnectionRequest(BaseModel):
    """Schema for connecting an app to a channel"""
    app_id: str = Field(..., description="ID of the app to connect")
    channel_id: str = Field(..., description="ID of the channel to connect to")
    connection_name: Optional[str] = Field(None, max_length=255, description="Name for this connection")
    connection_settings: Optional[Union[str, Dict[str, Any]]] = Field(None, description="JSON string or object for connection settings")
    webhook_url: Optional[str] = Field(None, max_length=500, description="Webhook URL for the app")
    callback_url: Optional[str] = Field(None, max_length=500, description="Callback URL for the app")
    auto_sync: bool = Field(False, description="Whether to auto-sync with the app")
    sync_interval: int = Field(3600, ge=60, description="Sync interval in seconds") 