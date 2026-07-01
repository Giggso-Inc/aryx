"""
Workspace schemas for request/response validation
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    """Workspace creation request schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_public: bool = False
    ai_enabled: bool = True
    ai_provider: str = "openai"
    ai_model: str = "gpt-4"
    settings: Optional[Dict[str, Any]] = None
    workspace_type: Optional[str] = Field(None, max_length=50)


class WorkspaceUpdate(BaseModel):
    """Workspace update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_public: Optional[bool] = None
    is_active: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    workspace_type: Optional[str] = Field(None, max_length=50)


class WorkspaceResponse(BaseModel):
    """Workspace response schema"""
    id: str
    name: str
    description: Optional[str] = None
    company_id: str
    is_active: bool
    is_public: bool
    ai_enabled: bool
    ai_provider: str
    ai_model: str
    max_messages: int
    max_attachments: int
    workspace_type: Optional[str] = None
    user_id: Optional[str] = None
    created_by: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    bridge: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class WorkspaceList(BaseModel):
    """Workspace list response schema"""
    workspaces: List[WorkspaceResponse]
    total: int
    page: int
    size: int


class WorkspaceStats(BaseModel):
    """Workspace statistics schema"""
    workspace_id: str
    total_messages: int
    total_threads: int
    total_attachments: int
    ai_responses_count: int
    last_activity: Optional[datetime] = None 
