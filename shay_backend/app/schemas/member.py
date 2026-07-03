"""
Pydantic schemas for GGMember (unified workspace / channel / thread membership).
"""

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ScopeLevel = Literal["workspace", "channel", "thread"]


class MemberCreate(BaseModel):
    """Schema for adding a member at any scope level."""

    user_id:      UUID
    level:        ScopeLevel
    workspace_id: Optional[UUID] = None
    channel_id:   Optional[UUID] = None
    thread_id:    Optional[UUID] = None
    role:         str            = Field("member", description="member | admin | viewer")
    permissions:  Optional[Dict[str, Any]] = None
    invited_by:   Optional[UUID] = None

    @model_validator(mode="after")
    def validate_exclusive_arc(self) -> "MemberCreate":
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


class MemberUpdate(BaseModel):
    """Schema for updating an existing membership."""

    role:        Optional[str]             = None
    is_active:   Optional[bool]            = None
    permissions: Optional[Dict[str, Any]]  = None
    joined_at:   Optional[datetime]        = None


class MemberResponse(BaseModel):
    """Schema for membership response."""

    id:           str
    user_id:      str
    level:        str
    workspace_id: Optional[str] = None
    channel_id:   Optional[str] = None
    thread_id:    Optional[str] = None
    role:         str
    is_active:    bool
    permissions:  Optional[Dict[str, Any]] = None
    invited_by:   Optional[str]            = None
    joined_at:    Optional[datetime]       = None
    created_at:   Optional[datetime]       = None
    updated_at:   Optional[datetime]       = None

    class Config:
        from_attributes = True


class MemberList(BaseModel):
    """Paginated list of members."""

    members: list[MemberResponse]
    total:   int
    page:    int
    size:    int


class EffectiveRoleResponse(BaseModel):
    """Response for the effective-role resolution endpoint."""

    user_id:        str
    effective_role: Optional[str]
    has_access:     bool
    resolved_at:    Optional[str] = None  # level at which role was resolved
