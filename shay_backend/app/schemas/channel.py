"""
Channel schemas for request/response validation
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_serializer
from uuid import UUID


class ChannelCreate(BaseModel):
    """Channel creation request schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    workspace_tag: Optional[str] = Field(None, min_length=1, max_length=255)  # Tag/workspace name (optional if workspace_id provided)
    workspace_id: Optional[str] = Field(None, description="Existing workspace ID (optional if workspace_tag provided)")
    is_public: bool = False
    is_archived: bool = False  # Default to false for new channels
    ai_enabled: bool = True
    channel_settings: Optional[Dict[str, Any]] = None  # Changed from settings to channel_settings
    channel_tags: Optional[List[str]] = None  # Optional; stored as null in DB when not provided or empty
    channel_sub_tags: Optional[List[str]] = None  # Optional; stored as null in DB when not provided or empty


class ChannelUpdate(BaseModel):
    """Channel update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_public: Optional[bool] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None  # Allow updating archived status
    ai_enabled: Optional[bool] = None
    channel_settings: Optional[Dict[str, Any]] = None  # Changed from settings to channel_settings
    channel_tags: Optional[List[str]] = None  # Optional; null in DB when not provided or empty
    channel_sub_tags: Optional[List[str]] = None  # Optional; null in DB when not provided or empty


class ChannelResponse(BaseModel):
    """Channel response schema"""
    id: Union[str, UUID]
    name: str
    description: Optional[str] = None
    channel_tags: Optional[List[str]] = None  # Optional; null when no tags
    channel_sub_tags: Optional[List[str]] = None  # Optional; null when no sub-tags
    workspace_name: Optional[str] = None
    workspace_id: Union[str, UUID]
    #workspace_name: str  # Include workspace name for convenience
    company_id: Union[str, UUID]
    is_active: bool
    is_public: bool
    is_archived: bool = False  # Default to false, shows archived status
    ai_enabled: bool
    channel_settings: Optional[Dict[str, Any]] = None  # Changed from settings to channel_settings
    message_count: int
    last_message_at: Optional[datetime] = None
    # Channel metrics
    total_apps_connected: int = 0  # Total apps connected to this channel
    total_users: int = 0  # Total users in this channel
    total_datasources: int = 0  # Total datasources added to this channel
    # App and datasource information
    app: Optional[List[Dict[str, Any]]] = None  # App information if connected (array of all apps)
    datasource: Optional[List[Dict[str, Any]]] = None  # Datasource information if available (array of all datasources)
    # Agent information
    agent_count: int = 0  # Number of agents in the channel
    agent_names: Dict[str, Any] = {}  # Names of agents in the channel
    # Workflow information
    workflow_count: int = 0  # Number of workflows in the channel
    # Task and Approval counts
    task_count: int = 0  # Total number of tasks in the channel
    approval_count: int = 0  # Total number of approvals in the channel
    # Channel type and provider (for email channels)
    channel_type: Optional[Union[int, str]] = None  # Channel type: "email" for email channels (string)
    provider: Optional[str] = None  # Provider for email channels (from AppAccount connection_settings)
    created_at: datetime
    updated_at: datetime
    
    @field_serializer('id', 'workspace_id', 'company_id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)
    
    class Config:
        from_attributes = True


class ChannelList(BaseModel):
    """Channel list response schema"""
    channels: List[ChannelResponse]
    total: int
    page: int
    size: int
    # When is_archived=false, true if the user/company has at least one archived channel (for "Show archived" tab)
    has_archived_channels: bool = False


class WorkspaceTagResponse(BaseModel):
    """Workspace tag response schema for listing available tags"""
    id: Union[str, UUID]
    name: str
    description: Optional[str] = None
    channel_count: int
    created_at: datetime
    
    @field_serializer('id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)
    
    class Config:
        from_attributes = True


class WorkspaceTagList(BaseModel):
    """Workspace tag list response schema"""
    tags: List[WorkspaceTagResponse]
    total: int
    page: int
    size: int 